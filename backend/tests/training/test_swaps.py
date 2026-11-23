"""Choosing a replacement (ADR 0020): pure, with the real library."""

import itertools

import pytest

from lock_in_mode_api.models.enums import (
    FitnessLevel,
    Goal,
    Location,
    MovementSlot,
    ShoulderDay,
)
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import IMPACT_ORDER, PlanAnswers
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import build_block
from lock_in_mode_api.training.swaps import another, replacement

LIBRARY = load_library().exercises
BY_SLUG = {e.slug: e for e in LIBRARY}


def _answers(
    location: Location = Location.HOME,
    equipment: tuple[str, ...] = (),
    level: FitnessLevel = FitnessLevel.BEGINNER,
    limits: tuple[str, ...] = (),
) -> PlanAnswers:
    return PlanAnswers(
        goal=Goal.BUILD_MUSCLE,
        level=level,
        location=location,
        equipment=equipment,
        limits=limits,
        days_per_week=3,
        minutes_per_session=45,
        women_home_track=False,
        prefers_bro_split=False,
        shoulder_day=ShoulderDay.PUSH,
        needs_low_intensity=False,
    )


PROFILES = [
    _answers(),
    _answers(equipment=("dumbbells",)),
    _answers(equipment=("resistance_bands", "pull_up_bar"), level=FitnessLevel.EXPERIENCED),
    _answers(location=Location.GYM, level=FitnessLevel.SOME_EXPERIENCE),
    _answers(location=Location.GYM, limits=("knees", "shoulders")),
]


def test_a_stand_in_does_the_same_job_and_is_never_harder_on_the_body() -> None:
    """Every exercise each profile can do: the stand-in has the same movement and the same
    kind of target, no more impact, and isn't the painful one or one already in use."""
    checked = 0
    for answers in PROFILES:
        picker = Picker(answers, LIBRARY)
        for painful, used_one in itertools.product(picker.usable, [None, *picker.usable[:3]]):
            used = set() if used_one is None else {used_one.slug}
            stand_in = replacement(picker, painful, used)
            if stand_in is None:
                continue
            checked += 1
            assert stand_in.slug != painful.slug and stand_in.slug not in used
            assert stand_in.movement_slot == painful.movement_slot
            assert stand_in.is_timed == painful.is_timed
            assert IMPACT_ORDER[stand_in.impact] <= IMPACT_ORDER[painful.impact]
            assert stand_in in picker.usable  # safe for them: kit, no caution
    assert checked > 1000


def test_same_or_easier_comes_first() -> None:
    picker = Picker(_answers(), LIBRARY)
    push_up = BY_SLUG["push-up"]

    stand_in = replacement(picker, push_up, set())

    assert stand_in is not None and stand_in.difficulty <= push_up.difficulty


def test_a_swapped_out_exercise_is_never_offered_or_planned() -> None:
    answers = _answers()
    first = Picker(answers, LIBRARY)
    push_up = BY_SLUG["push-up"]
    favourite = replacement(first, push_up, set())
    assert favourite is not None

    picker = Picker(answers, LIBRARY, excluded={favourite.slug})

    assert favourite.slug not in picker.by_slug
    assert replacement(picker, push_up, set()) != favourite
    for answers in PROFILES:
        routine = choose_routine(answers)
        everything = {
            e.slug
            for week in build_block(answers, routine, LIBRARY, 4, recovery_week=True)
            for w in week
            for e in (*w.warm_up, *w.exercises, *w.finisher, *w.cool_down)
        }
        banned = frozenset(sorted(everything)[::3])  # every third exercise they'd get
        block = build_block(answers, routine, LIBRARY, 4, recovery_week=True, excluded=banned)
        planned = {
            e.slug
            for week in block
            for w in week
            for e in (*w.warm_up, *w.exercises, *w.finisher, *w.cool_down)
        }
        assert not planned & banned


def test_show_another_walks_through_every_option() -> None:
    picker = Picker(_answers(location=Location.GYM), LIBRARY)
    start = next(e for e in picker.usable if e.movement_slot == MovementSlot.HORIZONTAL_PUSH)
    seen = [start]
    current = start
    for _ in range(40):
        nxt = another(picker, current, set())
        assert nxt is not None
        if nxt == start:
            break
        assert nxt not in seen  # never bounces back before every option was shown
        seen.append(nxt)
        current = nxt
    assert len(seen) >= 3


def test_show_another_with_no_other_option() -> None:
    picker = Picker(_answers(location=Location.GYM), LIBRARY)
    start = next(e for e in picker.usable if e.movement_slot == MovementSlot.HORIZONTAL_PUSH)
    everyone_else = {e.slug for e in picker.usable if e.slug != start.slug}

    assert another(picker, start, everyone_else) is None
    assert replacement(picker, start, everyone_else) is None


@pytest.mark.parametrize("answers", PROFILES)
def test_banning_every_option_leaves_nothing(answers: PlanAnswers) -> None:
    picker = Picker(answers, LIBRARY)
    painful = picker.usable[0]
    others = {
        e.slug
        for e in picker.usable
        if e.movement_slot == painful.movement_slot and e.slug != painful.slug
    }

    banned = Picker(answers, LIBRARY, excluded=others)

    assert replacement(banned, painful, set()) is None

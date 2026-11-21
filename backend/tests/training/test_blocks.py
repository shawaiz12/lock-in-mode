"""Whole training blocks (ADR 0017): build-up weeks, the recovery week, fresh small moves
each block, the saved answers, and moving a skipped strength test. Real library."""

import itertools
import math
import typing
from collections.abc import Sequence
from dataclasses import dataclass, fields

import pytest

from lock_in_mode_api.models.enums import (
    BodyLimit,
    Equipment,
    FitnessLevel,
    Goal,
    Location,
    ShoulderDay,
    WorkoutFormat,
)
from lock_in_mode_api.models.enums import SessionKind as S
from lock_in_mode_api.seed.schema import SeedExercise, load_library
from lock_in_mode_api.training.exercise_rules import can_do, cautions
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import (
    BLOCK_WEEKS,
    BUILD_WEEKS,
    RECOVERY_REPS_IN_RESERVE,
    BuildInputs,
    PlanAnswers,
    Workout,
)
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import as_test_workout, build_block
from lock_in_mode_api.training.templates import STRENGTH_KINDS, template

LIBRARY: Sequence[SeedExercise] = load_library().exercises
BY_SLUG = {e.slug: e for e in LIBRARY}


@dataclass(frozen=True)
class Answers:
    goal: Goal = Goal.BUILD_MUSCLE
    level: FitnessLevel = FitnessLevel.SOME_EXPERIENCE
    location: Location = Location.GYM
    equipment: tuple[str, ...] = ()
    days_per_week: int = 4
    minutes_per_session: int | None = 60
    needs_low_intensity: bool = False
    prefers_bro_split: bool = False
    shoulder_day: ShoulderDay = ShoulderDay.PUSH
    limits: tuple[str, ...] = ()
    women_home_track: bool = False


def _block(
    answers: Answers, block_number: int = 1, first_block: bool = False
) -> list[list[Workout]]:
    """A full block, as the service saves it."""
    return build_block(
        answers,
        choose_routine(answers),
        LIBRARY,
        BUILD_WEEKS,
        first_block,
        block_number=block_number,
        recovery_week=True,
    )


def _all(block: list[list[Workout]]) -> list[Workout]:
    return [w for week in block for w in week]


# --- block shape --------------------------------------------------------------------


def test_a_block_is_four_build_up_weeks_and_one_recovery_week() -> None:
    block = _block(Answers())

    assert len(block) == BLOCK_WEEKS == 5
    assert [all(w.recovery for w in week) for week in block] == [False] * 4 + [True]


def test_every_level_gets_the_same_block_length() -> None:
    for level in FitnessLevel:
        assert len(_block(Answers(level=level))) == BLOCK_WEEKS


# --- the recovery week (KB section 10) -------------------------------------------------


@pytest.mark.parametrize(
    "answers",
    [
        Answers(),  # gym, straight sets
        Answers(goal=Goal.LOSE_FAT, level=FitnessLevel.BEGINNER, location=Location.HOME,
                days_per_week=3, minutes_per_session=20),  # supersets + finishers
        Answers(goal=Goal.STAMINA, days_per_week=5, minutes_per_session=30),  # circuits, HIIT
        Answers(goal=Goal.STAY_ACTIVE, minutes_per_session=10, days_per_week=5),  # walks
    ],
    ids=["gym", "lose-fat-home", "stamina", "stay-active"],
)  # fmt: skip
def test_recovery_week_keeps_the_exercises_and_halves_the_work(answers: Answers) -> None:
    # Building 5 normal weeks makes the same picks, so week 5 is the recovery week
    # before it was made lighter.
    normal = build_block(answers, choose_routine(answers), LIBRARY, BLOCK_WEEKS)[-1]
    recovery = _block(answers)[-1]

    for before, after in zip(normal, recovery, strict=True):
        assert before.title == after.title
        assert after.total_minutes <= before.total_minutes
        steady = before.format in (WorkoutFormat.CONTINUOUS, WorkoutFormat.FLOW)
        for part in ("warm_up", "exercises", "finisher", "cool_down"):
            for old, new in zip(getattr(before, part), getattr(after, part), strict=True):
                assert new.slug == old.slug
                if part in ("warm_up", "cool_down") or (steady and part == "exercises"):
                    assert new == old  # easy already: unchanged
                elif old.reps_in_reserve is not None:  # strength
                    assert new.sets == math.ceil(old.sets / 2)
                    assert new.reps_in_reserve == max(old.reps_in_reserve, RECOVERY_REPS_IN_RESERVE)
                else:  # intervals
                    assert new.sets == math.ceil(old.sets / 2)
                    assert old.effort is not None and new.effort is not None
                    assert new.effort < old.effort or new.effort == 3


def test_the_strength_test_is_never_in_the_recovery_week() -> None:
    # Stamina, 2 days: circuits only. The test lands in the first one, never in week 5.
    block = _block(Answers(goal=Goal.STAMINA, days_per_week=2), first_block=True)

    tests = [w for w in _all(block) if any(e.test for e in w.exercises)]
    assert len(tests) == 1
    assert not tests[0].recovery


# --- fresh small moves each block (ADR 0017, KB section 10) -----------------------------


def _picks_by_slot(answers: Answers, block_number: int) -> dict[tuple[str, int], str]:
    """Week 1 picks keyed by (title, slot position), for strength workouts."""
    week = _block(answers, block_number)[0]
    return {
        (w.title, i): e.slug
        for w in week
        if w.kind in STRENGTH_KINDS
        for i, e in enumerate(w.exercises)
    }


def test_big_lifts_stay_and_small_moves_change_in_the_next_block() -> None:
    answers = Answers(minutes_per_session=None)  # no limit: every slot is filled
    first, second = _picks_by_slot(answers, 1), _picks_by_slot(answers, 2)

    week = _block(answers)[0]
    main_slots = {
        (w.title, i)
        for w in week
        if w.kind in STRENGTH_KINDS
        for i, slot in enumerate(s for s in template(w.kind, w.letter, answers.shoulder_day))
        if slot.main
    }
    assert main_slots
    for key in main_slots & first.keys():
        assert first[key] == second[key], key
    changed = [key for key in first.keys() - main_slots if first[key] != second.get(key)]
    assert len(changed) >= 5  # most small slots have more than 3 options in a gym


def test_block_three_comes_back_to_block_one_when_there_are_six_options() -> None:
    answers = Answers(minutes_per_session=None)
    first, third = _picks_by_slot(answers, 1), _picks_by_slot(answers, 3)

    same = sum(first[key] == third.get(key) for key in first)
    assert same >= len(first) * 0.8  # (a few slots have 4 or 5 options and wrap differently)


def test_same_answers_and_block_number_give_the_same_block() -> None:
    answers = Answers(goal=Goal.LOSE_FAT, days_per_week=5)

    assert _block(answers, 2) == _block(answers, 2)


# --- the saved answers -------------------------------------------------------------------


def test_plan_answers_hold_every_answer_the_generator_reads() -> None:
    # A new profile field the generator reads must be saved with the plan too,
    # or changing it wouldn't start a new block.
    assert {f.name for f in fields(PlanAnswers)} == typing.get_protocol_members(BuildInputs)


def test_plan_answers_survive_the_round_trip_through_json() -> None:
    answers = PlanAnswers.of(
        Answers(
            location=Location.HOME,
            equipment=(Equipment.DUMBBELLS,),
            limits=(BodyLimit.KNEES,),
            minutes_per_session=None,
            shoulder_day=ShoulderDay.LEGS,
        )
    )

    assert PlanAnswers.from_json(answers.to_json()) == answers


def test_a_block_built_from_saved_answers_matches_one_built_from_the_profile() -> None:
    profile = Answers(goal=Goal.STRENGTH, location=Location.HOME, equipment=("dumbbells",))
    saved = PlanAnswers.from_json(PlanAnswers.of(profile).to_json())

    assert _block(profile) == build_block(
        saved, choose_routine(saved), LIBRARY, BUILD_WEEKS, recovery_week=True
    )


# --- moving a skipped strength test (ADR 0017) ----------------------------------------


@pytest.mark.parametrize(
    "answers",
    [
        Answers(level=FitnessLevel.BEGINNER, location=Location.HOME, minutes_per_session=30),
        Answers(level=FitnessLevel.BEGINNER),  # gym: weighted lifts keep their reps
        Answers(location=Location.HOME, equipment=(Equipment.PULL_UP_BAR,)),
    ],
    ids=["home-bodyweight", "gym", "home-pull-up-bar"],
)
def test_moving_the_test_gives_the_same_workout_as_building_it_there(answers: Answers) -> None:
    routine = choose_routine(answers)
    plain = build_block(answers, routine, LIBRARY, 1)[0]
    tested = build_block(answers, routine, LIBRARY, 1, first_block=True)[0]
    position = next(i for i, w in enumerate(plain) if w.kind in STRENGTH_KINDS)

    moved = as_test_workout(plain[position].exercises, Picker(answers, LIBRARY))

    assert moved == list(tested[position].exercises)
    assert any(e.test for e in moved)


def test_moving_the_test_twice_changes_nothing_more() -> None:
    answers = Answers(level=FitnessLevel.BEGINNER, location=Location.HOME)
    picker = Picker(answers, LIBRARY)
    main = build_block(answers, choose_routine(answers), LIBRARY, 1)[0][0].exercises

    once = as_test_workout(main, picker)
    assert as_test_workout(once, picker) == once


# --- every block is safe, on time, and tests only once ---------------------------------

SETUPS = [
    (Location.GYM, ()),
    (Location.HOME, ()),
    (Location.HOME, (Equipment.DUMBBELLS, Equipment.PULL_UP_BAR, Equipment.RESISTANCE_BANDS)),
]


def _problems(answers: BuildInputs, block: list[list[Workout]]) -> list[str]:
    found = []
    workouts = _all(block)
    if sum(any(e.test for e in w.exercises) for w in workouts) > 1:
        found.append("more than one test workout")
    for workout in workouts:
        minutes = answers.minutes_per_session
        if minutes is not None and workout.total_minutes > minutes:
            found.append(f"{workout.title}: {workout.total_minutes} min")
        if not workout.exercises:
            found.append(f"{workout.title}: empty")
        slugs = [e.slug for e in workout.exercises]
        if len(slugs) != len(set(slugs)):
            found.append(f"{workout.title}: same move twice")
        parts = (workout.warm_up, workout.exercises, workout.finisher, workout.cool_down)
        for move in itertools.chain(*parts):
            exercise = BY_SLUG[move.slug]
            if not can_do(exercise, answers) or cautions(exercise, answers):
                found.append(f"{workout.title}: {move.slug} unsafe")
            if move.sets < 1:
                found.append(f"{workout.title}: {move.slug} has no sets")
        if workout.recovery:
            for move in workout.exercises:
                rir = move.reps_in_reserve
                if rir is not None and rir < RECOVERY_REPS_IN_RESERVE:
                    found.append(f"{workout.title}: {move.slug} too hard for recovery")
    return found


@pytest.mark.parametrize("goal", list(Goal))
def test_every_block_is_safe_on_time_and_tests_once(goal: Goal) -> None:
    problems = []
    for level, (location, kit), days, minutes, limits, low, block_number in itertools.product(
        FitnessLevel,
        SETUPS,
        [3, 5],
        [20, None],
        [(), (BodyLimit.KNEES, BodyLimit.BACK, BodyLimit.SHOULDERS)],
        [False, True],
        [1, 2],
    ):
        answers = Answers(goal, level, location, kit, days, minutes, low, limits=limits)
        block = _block(answers, block_number, first_block=block_number == 1)
        problems += [(answers, block_number, p) for p in _problems(answers, block)]

    assert problems == []


def test_hiit_and_cardio_are_never_the_test() -> None:
    block = _block(Answers(goal=Goal.STAMINA, days_per_week=5), first_block=True)
    for workout in _all(block):
        if workout.kind in (S.HIIT, S.STEADY_CARDIO, S.LONG_CARDIO, S.EASY_CARDIO):
            assert not any(e.test for e in workout.exercises)

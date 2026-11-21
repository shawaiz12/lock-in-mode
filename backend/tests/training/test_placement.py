"""The strength test places the user per movement (KB section 2, ADR 0018). Real library."""

import itertools

import pytest

from lock_in_mode_api.models.enums import BodyLimit, Equipment, FitnessLevel, Goal, Location
from lock_in_mode_api.models.enums import MovementSlot as M
from lock_in_mode_api.training.placement import RUNG_BY_RESULT, placed_exercise
from lock_in_mode_api.training.plan_types import BUILD_WEEKS, is_weighted
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import TEST_MOVES, build_block
from tests.training.test_blocks import BY_SLUG, LIBRARY, SETUPS, Answers, _all, _problems


@pytest.mark.parametrize(
    ("movement", "result", "slug"),
    [
        (M.HORIZONTAL_PUSH, 0, "incline-push-up"),
        (M.HORIZONTAL_PUSH, 4, "knee-push-up"),
        (M.HORIZONTAL_PUSH, 5, "push-up"),
        (M.HORIZONTAL_PUSH, 14, "push-up"),
        (M.HORIZONTAL_PUSH, 15, "decline-push-up"),
        (M.HORIZONTAL_PUSH, 30, "archer-push-up"),
        (M.SQUAT, 9, "chair-squat"),
        (M.SQUAT, 10, "bodyweight-squat"),
        (M.SQUAT, 25, "one-and-a-half-squat"),
        (M.BRACE, 19, "knee-plank"),
        (M.BRACE, 20, "plank"),
        (M.BRACE, 60, "plank-shoulder-taps"),
        (M.VERTICAL_PULL, 0, "negative-pull-up"),
        (M.VERTICAL_PULL, 5, "chin-up"),
        (M.VERTICAL_PULL, 6, "pull-up"),
    ],
)
def test_kb_section_2_thresholds(movement: M, result: int, slug: str) -> None:
    assert placed_exercise(movement, result) == slug


def test_untested_movements_place_nothing() -> None:
    assert placed_exercise(M.HINGE, 30) is None


def test_every_tested_movement_has_a_ladder_of_real_bodyweight_moves() -> None:
    assert set(RUNG_BY_RESULT) == set(TEST_MOVES)
    for movement, rows in RUNG_BY_RESULT.items():
        exercises = [BY_SLUG[slug] for _, slug in rows]
        assert all(e.movement_slot == movement and not is_weighted(e) for e in exercises)
        assert [e.difficulty for e in exercises] == sorted(e.difficulty for e in exercises)
        assert [minimum for minimum, _ in rows] == sorted({minimum for minimum, _ in rows})


def _bodyweight_difficulties(answers: Answers, rungs: dict[M, int], movement: M) -> set[int]:
    block = build_block(answers, choose_routine(answers), LIBRARY, 1, rungs=rungs)
    return {
        BY_SLUG[e.slug].difficulty
        for w in _all(block)
        for e in w.exercises
        if e.movement == movement and not is_weighted(BY_SLUG[e.slug])
    }


def test_a_rung_overrides_the_level_cap_both_ways() -> None:
    beginner = Answers(level=FitnessLevel.BEGINNER, location=Location.HOME, days_per_week=3)

    assert _bodyweight_difficulties(beginner, {}, M.HORIZONTAL_PUSH) == {1, 2}
    assert _bodyweight_difficulties(beginner, {M.HORIZONTAL_PUSH: 4}, M.HORIZONTAL_PUSH) == {4}
    assert _bodyweight_difficulties(beginner, {M.HORIZONTAL_PUSH: 1}, M.HORIZONTAL_PUSH) == {1}


def test_rungs_dont_apply_in_the_gym() -> None:
    # Gym users are placed by the weights they log (KB section 2), even if a rung is
    # left over from training at home.
    gym = Answers(level=FitnessLevel.BEGINNER, days_per_week=3)

    plain = build_block(gym, choose_routine(gym), LIBRARY, 1)
    placed = build_block(gym, choose_routine(gym), LIBRARY, 1, rungs={M.HORIZONTAL_PUSH: 5})

    assert plain == placed


@pytest.mark.parametrize("rung", [1, 5])
@pytest.mark.parametrize("goal", list(Goal))
def test_every_block_with_extreme_rungs_is_safe_and_on_time(goal: Goal, rung: int) -> None:
    rungs = dict.fromkeys(RUNG_BY_RESULT, rung)
    problems = []
    for level, (location, kit), days, minutes, limits, low in itertools.product(
        FitnessLevel,
        SETUPS,
        [3, 5],
        [20, None],
        [(), (BodyLimit.KNEES, BodyLimit.BACK, BodyLimit.SHOULDERS)],
        [False, True],
    ):
        answers = Answers(goal, level, location, kit, days, minutes, low, limits=limits)
        block = build_block(
            answers, choose_routine(answers), LIBRARY, BUILD_WEEKS, recovery_week=True, rungs=rungs
        )
        problems += [(answers, p) for p in _problems(answers, block)]

    assert problems == []


def test_home_pull_up_bar_user_with_no_pull_ups_gets_negatives() -> None:
    answers = Answers(location=Location.HOME, equipment=(Equipment.PULL_UP_BAR,))

    assert _bodyweight_difficulties(answers, {M.VERTICAL_PULL: 3}, M.VERTICAL_PULL) == {3}

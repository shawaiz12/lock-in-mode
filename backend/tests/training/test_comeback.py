"""The comeback rules (ADR 0021): bands, weeks, and how each week eases the numbers. Pure."""

import itertools

import pytest

from lock_in_mode_api.training import comeback as rules
from lock_in_mode_api.training.comeback import EASY_WEEK, RAMP, Ease
from lock_in_mode_api.training.progression import Served

ALL_EASES = (EASY_WEEK, *RAMP)
STEPS = (2.5, 4.0, 5.0)


@pytest.mark.parametrize(
    ("days", "weeks"),
    [(0, 0), (13, 0), (14, 1), (20, 1), (28, 1), (29, 3), (90, 3), (5000, 3)],
)
def test_bands(days: int, weeks: int) -> None:
    assert rules.weeks_for(days) == weeks


def test_a_comeback_week_is_the_workouts_of_a_week() -> None:
    weeks = [rules.week_of(i, per_week=3, weeks=3) for i in range(10)]
    assert weeks == [1, 1, 1, 2, 2, 2, 3, 3, 3, None]
    assert [rules.week_of(i, per_week=2, weeks=1) for i in range(3)] == [1, 1, None]


def test_the_ease_of_each_week() -> None:
    assert rules.ease_for(1, 1) is EASY_WEEK
    assert [rules.ease_for(3, w) for w in (1, 2, 3)] == list(RAMP)


@pytest.mark.parametrize(
    ("ease", "expected"),
    [
        (EASY_WEEK, [1, 2, 2, 3, 4, 5]),  # 80%
        (RAMP[0], [1, 1, 2, 2, 3, 3]),  # 50%, halves up
        (RAMP[1], [1, 2, 2, 3, 4, 5]),  # 75%
        (RAMP[2], [1, 2, 3, 4, 5, 6]),  # 100%
    ],
)
def test_sets_round_to_the_nearest_whole_set(ease: Ease, expected: list[int]) -> None:
    assert [rules.eased_sets(sets, ease) for sets in range(1, 7)] == expected


@pytest.mark.parametrize(
    ("weight", "ease", "step", "expected"),
    [
        (20.0, EASY_WEEK, 2.5, 15.0),  # 17.0: dumbbells go 15 → 17.5, so 15
        (40.0, RAMP[0], 2.5, 25.0),  # 26.0 → 25.0
        (60.0, RAMP[0], 5.0, 35.0),  # 39.0 → 35.0
        (60.0, RAMP[2], 5.0, 50.0),  # 54.0 → 50.0
        (16.0, RAMP[1], 4.0, 12.0),  # 12.8 → 12.0
        (2.5, RAMP[0], 2.5, 2.5),  # never below one step
        (2.0, RAMP[0], 2.5, 2.0),  # ...and never heavier than before
    ],
)
def test_weights_round_down_to_a_weight_that_exists(
    weight: float, ease: Ease, step: float, expected: float
) -> None:
    assert rules.eased_weight(weight, ease, step) == expected


def test_holds_get_shorter_but_never_under_10_seconds() -> None:
    assert rules.eased_seconds(30, RAMP[0]) == 20
    assert rules.eased_seconds(30, RAMP[1]) == 25
    assert rules.eased_seconds(15, RAMP[0]) == 10
    assert rules.eased_seconds(8, RAMP[0]) == 8  # already under the floor: left alone
    assert rules.eased_seconds(30, EASY_WEEK) == 30


def test_intervals_get_easier_but_never_under_3() -> None:
    assert rules.eased_effort(7, EASY_WEEK) == 5
    assert rules.eased_effort(4, RAMP[0]) == 3
    assert rules.eased_effort(2, RAMP[0]) == 2
    assert rules.eased_effort(7, RAMP[2]) == 7


def test_ramp_weeks_aim_at_the_bottom_of_the_range() -> None:
    served = Served(sets=3, reps_min=10, reps_max=12, seconds=None, weight_kg=None)
    week_1 = rules.ease(served, RAMP[0], planned_reps_min=8, timed=False, weight_step=2.5)
    week_3 = rules.ease(served, RAMP[2], planned_reps_min=8, timed=False, weight_step=2.5)
    assert (week_1.sets, week_1.reps_min, week_1.reps_max) == (2, 8, 12)
    assert (week_3.sets, week_3.reps_min) == (3, 10)  # "too easy" bonus back


def test_a_hold_is_eased_in_seconds() -> None:
    served = Served(sets=4, reps_min=None, reps_max=None, seconds=45, weight_kg=None)
    eased = rules.ease(served, RAMP[0], planned_reps_min=None, timed=True, weight_step=2.5)
    assert (eased.sets, eased.seconds) == (2, 35)


def test_easing_never_makes_anything_harder() -> None:
    """Every ease, over a wide grid of served numbers: nothing goes up, nothing breaks."""
    grid = itertools.product(
        range(1, 7),  # sets
        (None, 5, 8, 10, 12),  # reps_min (bonus included)
        (None, 30, 45, 60),  # seconds
        (None, 2.0, 2.5, 7.5, 12.0, 22.5, 40.0, 100.0),  # weight
        STEPS,
        ALL_EASES,
    )
    for sets, reps_min, seconds, weight, step, ease in grid:
        reps_max = None if reps_min is None else reps_min + 4
        served = Served(sets, reps_min, reps_max, seconds, weight)
        planned_min = None if reps_min is None else max(1, reps_min - 2)
        eased = rules.ease(
            served, ease, planned_reps_min=planned_min, timed=seconds is not None, weight_step=step
        )
        assert 1 <= eased.sets <= sets
        assert eased.reps_max == reps_max
        if reps_min is not None:
            assert eased.reps_min is not None and eased.reps_min <= reps_min
        if seconds is not None:
            assert eased.seconds is not None and min(seconds, 10) <= eased.seconds <= seconds
        if weight is not None:
            assert eased.weight_kg is not None and 0 < eased.weight_kg <= weight
            # A real weight: whole steps, unless it was already under one step.
            assert eased.weight_kg == weight or round(eased.weight_kg / step, 6).is_integer()

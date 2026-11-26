"""XP and the Lock In level (ADR 0035): pure rules, worked examples."""

import uuid

import pytest

from lock_in_mode_api.training.xp import (
    BONUS_EVERY,
    Level,
    bests_xp,
    capped,
    gets_bonus,
    level_of,
    level_start,
    lucky,
    workout_xp,
)


@pytest.fixture(autouse=True)
def _no_lucky_bonus() -> None:
    """The real roll here (conftest switches it off everywhere else)."""


def test_levels_start_early_and_grow() -> None:
    starts = [level_start(n) for n in (1, 2, 3, 4, 5, 10, 11, 20)]
    assert starts == [0, 100, 300, 600, 1000, 4500, 5500, 14500]


@pytest.mark.parametrize(
    ("xp", "level", "into", "needed"),
    [
        (0, 1, 0, 100),
        (99, 1, 99, 100),
        (100, 2, 0, 200),
        (4499, 9, 899, 900),
        (4500, 10, 0, 1000),
        (14500, 20, 0, 1000),
    ],
)
def test_the_level_of_a_total(xp: int, level: int, into: int, needed: int) -> None:
    assert level_of(xp) == Level(level, into, needed)


@pytest.mark.parametrize(
    ("done", "planned", "xp"),
    [(0, 10, 0), (5, 10, 50), (10, 10, 100), (12, 10, 100), (1, 3, 33), (3, 0, 100)],
)
def test_a_workout_earns_its_share_of_the_sets(done: int, planned: int, xp: int) -> None:
    assert workout_xp(done, planned) == xp


def test_new_bests_pay_25_each_at_most_3() -> None:
    assert [bests_xp(n) for n in (0, 1, 3, 5)] == [0, 25, 75, 75]


def test_the_bonus_roll_is_about_1_in_8_and_always_the_same_for_a_workout() -> None:
    ids = [uuid.uuid5(uuid.NAMESPACE_DNS, f"workout-{n}") for n in range(8000)]
    share = sum(lucky(i) for i in ids) / len(ids)
    assert 1 / BONUS_EVERY - 0.02 < share < 1 / BONUS_EVERY + 0.02
    assert [lucky(i) for i in ids[:50]] == [lucky(i) for i in ids[:50]]


def test_never_two_bonuses_in_a_row() -> None:
    lucky_id = next(
        i for i in (uuid.uuid5(uuid.NAMESPACE_DNS, str(n)) for n in range(100)) if lucky(i)
    )
    assert gets_bonus(lucky_id, previous_had_bonus=False) is True
    assert gets_bonus(lucky_id, previous_had_bonus=True) is False


def test_only_days_a_week_plus_one_workouts_earn_xp() -> None:
    assert capped(trained_before_this_week=3, days_per_week=3) is False  # the 4th earns
    assert capped(trained_before_this_week=4, days_per_week=3) is True  # the 5th doesn't

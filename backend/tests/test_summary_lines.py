"""The "Your plan knows you" lines (ADR 0026): one per count, in order, never a 0 line,
singular for 1, and the number in each line is exactly the count."""

import re

import pytest

from lock_in_mode_api.services.sign_in_offer import summary_lines

KEYS = (
    "workouts_finished",
    "sets_logged",
    "exercises_with_own_numbers",
    "exercises_left_out",
    "strength_test_moves",
)


def test_every_line_in_order() -> None:
    assert summary_lines(
        workouts_finished=23,
        sets_logged=310,
        exercises_with_own_numbers=12,
        exercises_left_out=2,
        strength_test_moves=4,
    ) == [
        "23 workouts finished",
        "310 sets logged",
        "Your own numbers saved for 12 exercises",
        "2 exercises left out because they hurt",
        "Strength test: starting points for 4 moves",
    ]


def test_ones_are_singular() -> None:
    assert summary_lines(
        workouts_finished=1,
        sets_logged=1,
        exercises_with_own_numbers=1,
        exercises_left_out=1,
        strength_test_moves=1,
    ) == [
        "1 workout finished",
        "1 set logged",
        "Your own numbers saved for 1 exercise",
        "1 exercise left out because it hurt",
        "Strength test: starting points for 1 move",
    ]


def test_nothing_yet_means_no_lines() -> None:
    assert summary_lines(**dict.fromkeys(KEYS, 0)) == []


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("n", [0, 1, 2, 7, 1000])
def test_each_line_shows_its_own_count_and_only_when_above_0(key: str, n: int) -> None:
    lines = summary_lines(**{k: (n if k == key else 0) for k in KEYS})

    if n == 0:
        assert lines == []
    else:
        [line] = lines
        assert [int(x) for x in re.findall(r"\d+", line)] == [n]

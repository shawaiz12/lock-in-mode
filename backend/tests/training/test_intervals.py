"""Interval progression rules (ADR 0023): the step scale, each level's range, what counts
as good or short, runs of two, feedback pairs, comebacks and level changes."""

import pytest

from lock_in_mode_api.models.enums import Feedback, FitnessLevel
from lock_in_mode_api.training import intervals as rules
from lock_in_mode_api.training.conditioning import INTERVALS
from lock_in_mode_api.training.intervals import Direction, Move, State, Timing, Verdict
from lock_in_mode_api.training.level_up import WeekShape, what_changes

B, SE, EX = FitnessLevel.BEGINNER, FitnessLevel.SOME_EXPERIENCE, FitnessLevel.EXPERIENCED
GOOD, SHORT, NOTHING = Verdict.GOOD, Verdict.SHORT, Verdict.NOTHING


# --- the scale ----------------------------------------------------------------------------


def test_every_step_is_a_one_minute_round() -> None:
    assert [rules.timing(s) for s in range(5)] == [
        Timing(20, 40),
        Timing(25, 35),
        Timing(30, 30),
        Timing(35, 25),
        Timing(40, 20),
    ]
    with pytest.raises(ValueError):
        rules.timing(5)
    with pytest.raises(ValueError):
        rules.timing(-1)


@pytest.mark.parametrize("level", list(FitnessLevel))
def test_each_level_starts_on_the_timing_its_plan_is_built_with(level: FitnessLevel) -> None:
    built = INTERVALS[level]
    assert rules.start_timing(level) == Timing(built.work, built.rest)


def test_each_level_climbs_to_the_next_levels_start() -> None:
    assert rules.RANGES[B].top == rules.RANGES[SE].start
    assert rules.RANGES[SE].top == rules.RANGES[EX].start
    assert rules.RANGES[EX].top == rules.RANGES[EX].start == rules.TOP_STEP


def test_the_floor_is_one_step_below_the_start_never_below_20_40() -> None:
    assert {level: r.floor for level, r in rules.RANGES.items()} == {B: 0, SE: 1, EX: 3}


def test_timing_reads_as_on_and_off() -> None:
    assert str(rules.timing(3)) == "35 s on / 25 s off"


# --- what counts ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("planned", "ticked", "feedback", "expected"),
    [
        (10, 10, None, GOOD),
        (10, 10, Feedback.JUST_RIGHT, GOOD),
        (10, 10, Feedback.TOO_EASY, GOOD),
        (10, 10, Feedback.TOO_HARD, SHORT),  # all done, but too hard
        (10, 9, None, SHORT),
        (10, 9, Feedback.TOO_EASY, SHORT),  # what they did wins over the tap
        (10, 1, None, SHORT),
        (10, 0, None, NOTHING),  # a finisher left out for time
        (10, 0, Feedback.TOO_HARD, NOTHING),
        (0, 0, Feedback.TOO_EASY, NOTHING),  # no intervals in the workout
    ],
)
def test_verdict(planned: int, ticked: int, feedback: Feedback | None, expected: Verdict) -> None:
    assert rules.verdict(planned, ticked, feedback) == expected


# --- runs of two --------------------------------------------------------------------------


def test_two_good_in_a_row_is_one_step_up() -> None:
    first = rules.after_workout(SE, State(2), GOOD)
    assert first == Move(State(2, good_runs=1))

    second = rules.after_workout(SE, first.state, GOOD)
    assert second == Move(State(3), Direction.UP)


def test_two_short_in_a_row_is_one_step_down() -> None:
    first = rules.after_workout(SE, State(2), SHORT)
    assert first == Move(State(2, short_runs=1))

    assert rules.after_workout(SE, first.state, SHORT) == Move(State(1), Direction.DOWN)


def test_a_good_workout_clears_the_short_run_and_the_other_way() -> None:
    assert rules.after_workout(SE, State(2, short_runs=1), GOOD) == Move(State(2, good_runs=1))
    assert rules.after_workout(SE, State(2, good_runs=1), SHORT) == Move(State(2, short_runs=1))


def test_nothing_keeps_the_run() -> None:
    assert rules.after_workout(SE, State(2, good_runs=1), NOTHING) == Move(State(2, good_runs=1))


@pytest.mark.parametrize(("level", "top"), [(B, 2), (SE, 4), (EX, 4)])
def test_the_top_holds_and_the_run_starts_again(level: FitnessLevel, top: int) -> None:
    assert rules.after_workout(level, State(top, good_runs=1), GOOD) == Move(State(top))


@pytest.mark.parametrize(("level", "floor"), [(B, 0), (SE, 1), (EX, 3)])
def test_the_floor_holds_and_the_run_starts_again(level: FitnessLevel, floor: int) -> None:
    assert rules.after_workout(level, State(floor, short_runs=1), SHORT) == Move(State(floor))


# --- feedback pairs ------------------------------------------------------------------------


def test_a_too_easy_pair_steps_up_and_clears_the_runs() -> None:
    move = rules.after_workout(SE, State(2), GOOD)
    assert rules.with_pair(SE, move, GOOD, Feedback.TOO_EASY) == Move(State(3), Direction.UP)
    nothing = Move(State(2, short_runs=1))
    assert rules.with_pair(SE, nothing, NOTHING, Feedback.TOO_EASY) == Move(State(3), Direction.UP)


def test_a_too_hard_pair_steps_down() -> None:
    move = rules.after_workout(SE, State(3), SHORT)
    assert rules.with_pair(SE, move, SHORT, Feedback.TOO_HARD) == Move(State(2), Direction.DOWN)


def test_a_pair_never_moves_twice_in_one_workout() -> None:
    moved = rules.after_workout(SE, State(3, short_runs=1), SHORT)
    assert moved.direction == Direction.DOWN
    assert rules.with_pair(SE, moved, SHORT, Feedback.TOO_HARD) == moved
    up = rules.after_workout(SE, State(2, good_runs=1), GOOD)
    assert rules.with_pair(SE, up, GOOD, Feedback.TOO_EASY) == up


def test_rounds_missed_win_over_a_too_easy_pair() -> None:
    move = rules.after_workout(SE, State(2), SHORT)
    assert rules.with_pair(SE, move, SHORT, Feedback.TOO_EASY) == move


def test_a_pair_stops_at_the_top_and_the_floor() -> None:
    top = Move(State(4))
    assert rules.with_pair(SE, top, NOTHING, Feedback.TOO_EASY) == top
    floor = Move(State(0))
    assert rules.with_pair(B, floor, NOTHING, Feedback.TOO_HARD) == floor


def test_just_right_or_no_pair_changes_nothing() -> None:
    move = Move(State(2, good_runs=1))
    assert rules.with_pair(SE, move, GOOD, Feedback.JUST_RIGHT) == move
    assert rules.with_pair(SE, move, GOOD, None) == move


# --- level changes and comebacks -------------------------------------------------------


def test_nothing_saved_is_the_levels_start() -> None:
    assert rules.state_for(B, None) == State(0)
    assert rules.state_for(EX, None) == State(4)


def test_a_step_saved_for_another_level_is_the_new_levels_start() -> None:
    assert rules.state_for(SE, (B, State(1, good_runs=1))) == State(2)
    assert rules.state_for(B, (SE, State(4))) == State(0)
    assert rules.state_for(SE, (SE, State(3, short_runs=1))) == State(3, short_runs=1)


@pytest.mark.parametrize(("step", "eased", "served"), [(3, True, 2), (0, True, 0), (3, False, 3)])
def test_comebacks_serve_one_step_easier(step: int, eased: bool, served: int) -> None:
    assert rules.served_step(step, comeback_eased=eased) == served


# --- the level-up text (ADR 0022) ---------------------------------------------------------

LOW, HIGH = WeekShape(3, 30, intervals=True), WeekShape(3, 36, intervals=True)


def test_level_up_says_when_the_interval_timing_changes() -> None:
    lines = what_changes(
        LOW, HIGH, minutes=45, low_intensity=False, intervals=(Timing(20, 40), Timing(30, 30))
    )
    assert "Intervals: 20 s on / 40 s off → 30 s on / 30 s off." in lines


@pytest.mark.parametrize(
    ("now", "after", "timings"),
    [
        (LOW, HIGH, (Timing(30, 30), Timing(30, 30))),  # already at the new start
        (WeekShape(3, 30), HIGH, (Timing(20, 40), Timing(30, 30))),  # no intervals now
        (LOW, WeekShape(3, 36), (Timing(20, 40), Timing(30, 30))),  # none after
        (LOW, HIGH, None),
    ],
)
def test_no_intervals_line_otherwise(
    now: WeekShape, after: WeekShape, timings: tuple[Timing, Timing] | None
) -> None:
    lines = what_changes(now, after, minutes=45, low_intensity=False, intervals=timings)
    assert not any(line.startswith("Intervals") for line in lines)

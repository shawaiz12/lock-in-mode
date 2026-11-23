"""Interval progression (ADR 0023): HIIT and finishers get harder as the user does.

Every interval is one minute of work + rest. A step makes the work 5 s longer and the
rest 5 s shorter, so a round is still a minute: the workout gets harder, never longer.

    step        0        1        2        3        4
    work/rest   20/40    25/35    30/30    35/25    40/20

    level            starts  climbs to  can drop to
    beginner         0       2          0
    some experience  2       4          1
    experienced      4       4          3

Two good workouts in a row (every round ticked, no "too hard") = one step up; two short
ones (rounds missed, or "too hard") = one step down. A workout with no interval rounds
ticked at all counts as nothing. A pair of identical taps (ADR 0019) moves it too.
Pure rules: the progress service feeds them and saves what they return.
"""

from dataclasses import dataclass
from enum import StrEnum

from lock_in_mode_api.models.enums import Feedback, FitnessLevel

ROUND_SECONDS = 60
STEP_SECONDS = 5
TOP_STEP = 4
RUNS_TO_MOVE = 2  # good (or short) workouts in a row that move the step


@dataclass(frozen=True)
class Timing:
    work: int
    rest: int

    def __str__(self) -> str:
        return f"{self.work} s on / {self.rest} s off"


@dataclass(frozen=True)
class Range:
    start: int
    top: int
    floor: int


RANGES = {
    FitnessLevel.BEGINNER: Range(start=0, top=2, floor=0),
    FitnessLevel.SOME_EXPERIENCE: Range(start=2, top=4, floor=1),
    FitnessLevel.EXPERIENCED: Range(start=4, top=4, floor=3),
}


def timing(step: int) -> Timing:
    """Work and rest for a step: 20 s of work at step 0, 5 s more per step."""
    if not 0 <= step <= TOP_STEP:
        raise ValueError(f"interval step out of range: {step}")
    work = 20 + STEP_SECONDS * step
    return Timing(work, ROUND_SECONDS - work)


def start_timing(level: FitnessLevel) -> Timing:
    """The level's own timing (KB section 7), which the plan is built with."""
    return timing(RANGES[level].start)


@dataclass(frozen=True)
class State:
    """One user's interval progress, read for a level: the step, and the runs so far."""

    step: int
    good_runs: int = 0
    short_runs: int = 0


def state_for(level: FitnessLevel, saved: tuple[FitnessLevel, State] | None) -> State:
    """What applies at this level. Nothing saved, or saved for another level (a level-up
    or a new level in the profile) = the level's start, with no runs."""
    if saved is None or saved[0] != level:
        return State(RANGES[level].start)
    return saved[1]


def served_step(step: int, *, comeback_eased: bool) -> int:
    """The step a workout is served at. Comeback weeks that ease the effort (ADR 0021)
    serve one step easier, never below step 0; the saved step is untouched."""
    return max(0, step - 1) if comeback_eased else step


class Verdict(StrEnum):
    GOOD = "good"
    SHORT = "short"
    NOTHING = "nothing"


def verdict(planned_rounds: int, ticked_rounds: int, feedback: Feedback | None) -> Verdict:
    """How one workout's intervals went. Rounds count across every interval move.

    No round ticked = nothing (a finisher left out for time, ADR 0023 decision 6).
    What they did wins over the tap: rounds missed are short even after "too easy".
    """
    if planned_rounds <= 0 or ticked_rounds <= 0:
        return Verdict.NOTHING
    if ticked_rounds < planned_rounds or feedback == Feedback.TOO_HARD:
        return Verdict.SHORT
    return Verdict.GOOD


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class Move:
    state: State
    direction: Direction | None = None


def _up(level: FitnessLevel, step: int) -> int:
    return min(RANGES[level].top, step + 1)


def _down(level: FitnessLevel, step: int) -> int:
    return max(RANGES[level].floor, step - 1)


def after_workout(level: FitnessLevel, state: State, result: Verdict) -> Move:
    """Count the run; the second good (or short) one in a row moves the step. Runs start
    again after a move, and at the top or the floor (nothing to move to)."""
    if result == Verdict.NOTHING:
        return Move(state)
    if result == Verdict.GOOD:
        good = state.good_runs + 1
        if good < RUNS_TO_MOVE:
            return Move(State(state.step, good_runs=good))
        step = _up(level, state.step)
        return Move(State(step), Direction.UP if step != state.step else None)
    short = state.short_runs + 1
    if short < RUNS_TO_MOVE:
        return Move(State(state.step, short_runs=short))
    step = _down(level, state.step)
    return Move(State(step), Direction.DOWN if step != state.step else None)


def with_pair(level: FitnessLevel, move: Move, result: Verdict, pair: Feedback | None) -> Move:
    """A pair of identical taps moves the step one notch, unless this workout already
    moved it that way (ADR 0019's streak, applied to intervals). Rounds missed win over
    a "too easy" pair, as falling short wins in ADR 0019: it's what they actually did."""
    if pair == Feedback.TOO_EASY and move.direction is None and result != Verdict.SHORT:
        step = _up(level, move.state.step)
        if step != move.state.step:
            return Move(State(step), Direction.UP)
    if pair == Feedback.TOO_HARD and move.direction is None:
        step = _down(level, move.state.step)
        if step != move.state.step:
            return Move(State(step), Direction.DOWN)
    return move

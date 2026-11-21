"""Progression: what changes after a workout (ADR 0019, KB section 10). Pure: no database.

Each exercise a user has trained has a saved **target** (table `exercise_targets`): the
suggested weight, an extra or missing set, a hold length, a reps nudge. The saved plan
keeps the block's starting numbers; `serve` puts the two together when a workout is shown.

After a workout, `after_workout` reads the logged sets and the feedback tap and returns
the new target and what changed:

- **Double progression:** the top of the rep range on every set → one step up, reps start
  at the bottom again. Weights: one step heavier. Bodyweight: one extra set, then the
  harder move (home only: the next rung of the ladder). Holds: +5 s up to 60 s, then the
  harder move.
- **"Too easy" once:** aim 2 reps higher next time (holds: +5 s). **"Too hard" once:** no
  step up; repeat the same targets.
- **First set 3+ reps short** (holds: 10 s short) in two workouts of it running: one step
  back for that exercise.

`streak_fires` and `earns_recovery` decide the two whole-plan rules: the same tap twice in
a row steps every exercise up or back, and "too hard" on more than half of a week's
workouts brings the recovery week forward.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from lock_in_mode_api.models.enums import Equipment, Feedback, MovementSlot, ProgressChange

M = MovementSlot
C = ProgressChange

HOLD_STEP = 5  # seconds added per step up
HOLD_TOP = 60  # past this, a hold gets a harder variation instead (KB section 10)
HOLD_STEP_BACK = 10
HOLD_FLOOR = 10
EASY_REPS = 2  # one "too easy": aim this many reps higher next time
SHORT_REPS = 3  # the first set this many reps under the bottom of the range...
SHORT_SECONDS = 10  # ...or a hold this many seconds short...
SHORT_WORKOUTS = 2  # ...in this many workouts of that exercise in a row: one step back
MAX_EXTRA_SETS = 1
MIN_SET_CHANGE = -1
STEP_BACK_SHARE = 0.9  # stepping back a weight: about 10% lighter

LOWER_BODY = frozenset(
    {M.SQUAT, M.SINGLE_LEG, M.HINGE, M.BRIDGE, M.LEG_CURL, M.LEG_EXTENSION, M.CALVES, M.ADDUCTORS}
)
DUMBBELL_STEP = 2.5  # the next pair up
KETTLEBELL_STEP = 4.0
STACK_STEP = 5.0  # machines and cables: the next pin
BAR_UPPER_STEP = 2.5  # a 1.25 kg plate each side
BAR_LOWER_STEP = 5.0
_BARS = ("barbell", "ez bar", "trap bar", "smith")


# --- what is saved, planned and shown --------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One user's progress on one exercise. The defaults mean "as planned"."""

    weight_kg: float | None = None  # suggested working weight
    set_change: int = 0  # -1, 0 or +1 sets compared with the plan
    seconds: int | None = None  # holds: the hold to aim for
    reps_bonus: int = 0  # one "too easy": the bottom of the range is this much higher
    short_runs: int = 0  # workouts in a row with the first set well short


@dataclass(frozen=True)
class Planned:
    """The numbers saved in the plan (planned_exercises)."""

    sets: int
    reps_min: int | None
    reps_max: int | None
    seconds: int | None


@dataclass(frozen=True)
class Served:
    """What the user is asked to do this time: the plan with their progress applied."""

    sets: int
    reps_min: int | None
    reps_max: int | None
    seconds: int | None
    weight_kg: float | None


@dataclass(frozen=True)
class Logged:
    """One ticked set."""

    reps: int | None
    weight_kg: float | None
    seconds: int | None


@dataclass(frozen=True)
class Move:
    """What the rules need to know about the exercise and where it's done.

    `harder_rung` / `easier_rung`: the next difficulty up or down this user's ladder for
    this movement (home, bodyweight); None in the gym, for weights, or at the end of it.
    `can_change_sets`: False in a circuit, where every exercise shares the rounds.
    """

    timed: bool
    weight_step: float
    harder_rung: int | None = None
    easier_rung: int | None = None
    can_change_sets: bool = True


@dataclass(frozen=True)
class Step:
    """The new target, what changed (None: nothing), and a new rung for the movement."""

    target: Target
    change: ProgressChange | None = None
    rung: int | None = None


def serve(planned: Planned, target: Target | None, *, circuit: bool = False) -> Served:
    """The plan's numbers with the user's progress on top. Circuits keep their rounds."""
    if target is None:
        return Served(planned.sets, planned.reps_min, planned.reps_max, planned.seconds, None)
    sets = planned.sets if circuit else max(1, planned.sets + target.set_change)
    reps_min = planned.reps_min
    if reps_min is not None and planned.reps_max is not None:
        reps_min = min(reps_min + target.reps_bonus, planned.reps_max)
    seconds = planned.seconds
    if seconds is not None and target.seconds is not None:
        seconds = target.seconds
    return Served(sets, reps_min, planned.reps_max, seconds, target.weight_kg)


# --- step sizes --------------------------------------------------------------------------


def weight_step(equipment: Sequence[str], also_needs: str | None, movement: MovementSlot) -> float:
    """How much heavier one step is: the next weight a real gym has (user's choice).

    Dumbbells: the next pair (+2.5 kg). Kettlebells: +4 kg. Barbells: +2.5 kg upper body,
    +5 kg legs and hips. Machines and cables: the next pin (+5 kg).
    """
    lower = movement in LOWER_BODY
    needs = (also_needs or "").lower()
    if Equipment.DUMBBELLS in equipment:
        return DUMBBELL_STEP
    if "kettlebell" in needs:
        return KETTLEBELL_STEP
    if any(bar in needs for bar in _BARS):
        return BAR_LOWER_STEP if lower else BAR_UPPER_STEP
    if "machine" in needs or "cable" in needs:
        return STACK_STEP
    return BAR_LOWER_STEP if lower else BAR_UPPER_STEP


def _round_down(weight: float) -> float:
    return math.floor(weight * 2) / 2  # to 0.5 kg


def neighbour_rungs(difficulty: int, ladder: Iterable[int]) -> tuple[int | None, int | None]:
    """(easier, harder): the nearest difficulties below and above on this user's ladder."""
    rungs = set(ladder)
    easier = max((d for d in rungs if d < difficulty), default=None)
    harder = min((d for d in rungs if d > difficulty), default=None)
    return easier, harder


# --- one step up or back --------------------------------------------------------------


def _can_drop_a_set(move: Move, target: Target, served: Served) -> bool:
    return move.can_change_sets and target.set_change > MIN_SET_CHANGE and served.sets > 1


def _can_add_a_set(move: Move, target: Target) -> bool:
    return move.can_change_sets and target.set_change < MAX_EXTRA_SETS


def step_up(move: Move, target: Target, served: Served, weight: float | None) -> Step:
    """One notch harder. `weight`: what they lifted (None: no weight involved).

    A set taken away by a step back comes back first. Then: weights one step heavier
    (if they didn't take the last suggested jump, an extra set instead: their dumbbells
    may not go heavier); holds +5 s up to 60 s; bodyweight one extra set; then the
    harder move. Nothing left (the gym's hardest bodyweight move with its extra set):
    no change, the targets stay at the top.
    """
    fresh = replace(target, reps_bonus=0, short_runs=0)
    if move.can_change_sets and target.set_change < 0:
        return Step(replace(fresh, set_change=target.set_change + 1), C.EXTRA_SET)
    if move.timed:
        held = served.seconds or 0
        if held < HOLD_TOP:
            return Step(replace(fresh, seconds=min(HOLD_TOP, held + HOLD_STEP)), C.LONGER_HOLD)
        if move.harder_rung is not None:
            return Step(replace(fresh, seconds=None, set_change=0), C.HARDER_MOVE, move.harder_rung)
        if _can_add_a_set(move, target):
            return Step(replace(fresh, set_change=target.set_change + 1), C.EXTRA_SET)
        return Step(fresh)
    if weight is not None:
        if target.weight_kg is not None and weight < target.weight_kg:
            if _can_add_a_set(move, target):  # stayed lighter than suggested, and got there
                return Step(replace(fresh, set_change=target.set_change + 1), C.EXTRA_SET)
            return Step(fresh)
        heavier = replace(fresh, weight_kg=weight + move.weight_step, set_change=0)
        return Step(heavier, C.HEAVIER)
    if _can_add_a_set(move, target):
        return Step(replace(fresh, set_change=target.set_change + 1), C.EXTRA_SET)
    if move.harder_rung is not None:
        return Step(replace(fresh, set_change=0), C.HARDER_MOVE, move.harder_rung)
    return Step(fresh)


def step_back(move: Move, target: Target, served: Served, weight: float | None) -> Step:
    """One notch easier (KB section 10: -1 set, -1 rung or about 10% lighter).

    An extra set goes first. Then: weights about 10% lighter (at least one step);
    holds -10 s (not under 10 s); bodyweight one rung down. Last resort: one set fewer.
    """
    fresh = replace(target, reps_bonus=0, short_runs=0)
    if move.can_change_sets and target.set_change > 0:
        return Step(replace(fresh, set_change=0), C.FEWER_SETS)
    if move.timed:
        held = served.seconds or 0
        if held - HOLD_STEP_BACK >= HOLD_FLOOR:
            return Step(replace(fresh, seconds=held - HOLD_STEP_BACK), C.SHORTER_HOLD)
    elif weight is not None:
        lighter = min(weight - move.weight_step, _round_down(weight * STEP_BACK_SHARE))
        if lighter > 0:
            return Step(replace(fresh, weight_kg=lighter), C.LIGHTER)
    if move.easier_rung is not None and weight is None:
        return Step(replace(fresh, seconds=None, set_change=0), C.EASIER_MOVE, move.easier_rung)
    if _can_drop_a_set(move, target, served):
        return Step(replace(fresh, set_change=target.set_change - 1), C.FEWER_SETS)
    return Step(fresh)


# --- after one workout ------------------------------------------------------------------


def hit_the_top(move: Move, served: Served, logged: Mapping[int, Logged]) -> bool:
    """Every set asked for was ticked at the top of the range (holds: the full time)."""
    for number in range(1, served.sets + 1):
        done = logged.get(number)
        if done is None:
            return False
        if move.timed:
            if served.seconds is None or (done.seconds or 0) < served.seconds:
                return False
        elif served.reps_max is None or (done.reps or 0) < served.reps_max:
            return False
    return True


def fell_short(move: Move, served: Served, first: Logged) -> bool:
    """The first set was well short: 3+ reps under the bottom of the range, or 10 s."""
    if move.timed:
        return served.seconds is not None and (first.seconds or 0) <= served.seconds - SHORT_SECONDS
    return served.reps_min is not None and (first.reps or 0) <= served.reps_min - SHORT_REPS


def working_weight(target: Target, logged: Mapping[int, Logged]) -> float | None:
    """The lightest weight they logged (to be safe), else the suggested one, else None."""
    weights = [s.weight_kg for s in logged.values() if s.weight_kg]
    if weights:
        return min(weights)
    return target.weight_kg


def after_workout(
    move: Move,
    target: Target | None,
    served: Served,
    logged: Mapping[int, Logged],
    feedback: Feedback | None,
) -> Step:
    """The new target for one exercise after a (non-recovery) workout. `logged`: its sets
    by set number. Nothing logged: nothing learned, only a "too easy" nudge applies.
    """
    target = target or Target()
    weight = working_weight(target, logged) if not move.timed else None
    first = logged.get(1)
    if first is not None:
        runs = target.short_runs + 1 if fell_short(move, served, first) else 0
        if runs >= SHORT_WORKOUTS:
            return step_back(move, target, served, weight)
        target = replace(target, short_runs=runs)
    if logged and feedback != Feedback.TOO_HARD and hit_the_top(move, served, logged):
        return step_up(move, target, served, weight)
    if feedback == Feedback.TOO_EASY:
        if move.timed:
            held = served.seconds or 0
            if held < HOLD_TOP:
                longer = replace(target, seconds=min(HOLD_TOP, held + HOLD_STEP), reps_bonus=0)
                return Step(longer, C.LONGER_HOLD)
        elif (
            served.reps_min is not None
            and served.reps_max is not None
            and served.reps_min < served.reps_max
        ):
            return Step(replace(target, reps_bonus=EASY_REPS), C.MORE_REPS)
    return Step(replace(target, reps_bonus=0))


# --- whole-plan rules --------------------------------------------------------------------


def streak_fires(answers: Sequence[Feedback]) -> Feedback | None:
    """The same tap twice in a row: step every exercise up (too easy) or back (too hard).

    `answers`: the user's feedback taps, newest first, skipped taps left out. Fires on the
    2nd, 4th, 6th... identical tap in a row, so a third "too easy" is a single nudge again
    rather than a second jump straight after the first.
    """
    if not answers or answers[0] == Feedback.JUST_RIGHT:
        return None
    run = 0
    for answer in answers:
        if answer != answers[0]:
            break
        run += 1
    return answers[0] if run % 2 == 0 else None


def earns_recovery(too_hard: int, workouts_in_week: int) -> bool:
    """ "Too hard" on more than half of the week's workouts: the recovery week comes early."""
    return workouts_in_week > 0 and too_hard * 2 > workouts_in_week

"""Coming back after a break (ADR 0021, KB section 10). Pure: no database.

Time away is counted in whole days since the last ticked set. Three bands:

    under 14 days   carry on, nothing changes
    14 to 28 days   1 easy week
    over 28 days    a 3-week ramp back up

A comeback week is as many trained workouts as the user does in a week. The saved
progress (targets, weights, rungs) is never touched: `ease` makes the served numbers
lighter, and once the comeback is over they're the saved numbers again.

    week                sets   weights  bodyweight reps         holds        intervals
    easy week           80%    85%      as usual                as usual     effort -2
    ramp week 1         50%    65%      bottom of the range     10 s less    effort -2
    ramp week 2         75%    80%      bottom of the range     5 s less     effort -2
    ramp week 3         100%   90%      as usual                as usual     as usual
"""

import math
from dataclasses import dataclass

from lock_in_mode_api.training.plan_types import RECOVERY_EFFORT_DROP, RECOVERY_MIN_EFFORT
from lock_in_mode_api.training.progression import HOLD_FLOOR, Served

BREAK_DAYS = 14  # this many days away or more: a comeback
LONG_BREAK_DAYS = 28  # more than this: the 3-week ramp
EASY_WEEKS = 1
RAMP_WEEKS = 3


@dataclass(frozen=True)
class Ease:
    """How much lighter one comeback week is."""

    sets: float  # share of the served sets
    weight: float  # share of the suggested weight
    bottom_reps: bool  # aim at the bottom of the rep range (no "too easy" bonus)
    hold_cut: int  # seconds off a hold
    effort_drop: int  # points easier on the talk test (intervals, finishers)


EASY_WEEK = Ease(
    sets=0.8, weight=0.85, bottom_reps=False, hold_cut=0, effort_drop=RECOVERY_EFFORT_DROP
)
RAMP = (
    Ease(sets=0.5, weight=0.65, bottom_reps=True, hold_cut=10, effort_drop=RECOVERY_EFFORT_DROP),
    Ease(sets=0.75, weight=0.8, bottom_reps=True, hold_cut=5, effort_drop=RECOVERY_EFFORT_DROP),
    Ease(sets=1.0, weight=0.9, bottom_reps=False, hold_cut=0, effort_drop=0),
)


def weeks_for(away_days: int) -> int:
    """How many comeback weeks this break needs: 0 (carry on), 1 or 3."""
    if away_days < BREAK_DAYS:
        return 0
    if away_days <= LONG_BREAK_DAYS:
        return EASY_WEEKS
    return RAMP_WEEKS


def week_of(index: int, per_week: int, weeks: int) -> int | None:
    """The comeback week (from 1) of the comeback workout at `index` (from 0: the first
    workout trained after the break), or None once the comeback is over."""
    week = index // per_week + 1
    return week if 1 <= week <= weeks else None


def ease_for(weeks: int, week: int) -> Ease:
    """The easing of week `week` (from 1) of a comeback lasting `weeks` weeks."""
    if weeks == EASY_WEEKS:
        return EASY_WEEK
    return RAMP[week - 1]


def eased_sets(sets: int, ease: Ease) -> int:
    """Nearest whole set, halves up, never below 1 (or above what was asked)."""
    return min(sets, max(1, math.floor(sets * ease.sets + 0.5)))


def eased_weight(weight: float, ease: Ease, step: float) -> float:
    """Lighter, rounded down to a weight that exists (the exercise's step), never below
    one step and never heavier than before."""
    lighter = math.floor(weight * ease.weight / step + 1e-9) * step
    return min(weight, max(step, round(lighter, 2)))


def eased_seconds(seconds: int, ease: Ease) -> int:
    """A shorter hold, never under 10 s (or longer than before)."""
    return min(seconds, max(HOLD_FLOOR, seconds - ease.hold_cut))


def eased_effort(effort: int, ease: Ease) -> int:
    """Easier on the talk test, never under 3 (or harder than before)."""
    return min(effort, max(RECOVERY_MIN_EFFORT, effort - ease.effort_drop))


def ease(
    served: Served,
    ease: Ease,
    *,
    planned_reps_min: int | None,
    timed: bool,
    weight_step: float,
) -> Served:
    """One strength exercise's numbers for a comeback week.

    `planned_reps_min`: the plan's bottom of the range, before any "too easy" bonus.
    `timed`: a hold, eased in seconds rather than reps. Circuits ease their shared rounds
    with the same rule, so every exercise keeps the same number of rounds.
    """
    reps_min = served.reps_min
    if ease.bottom_reps and planned_reps_min is not None and reps_min is not None:
        reps_min = min(reps_min, planned_reps_min)
    seconds = served.seconds
    if timed and seconds is not None:
        seconds = eased_seconds(seconds, ease)
    weight = served.weight_kg
    if weight is not None:
        weight = eased_weight(weight, ease, weight_step)
    return Served(
        sets=eased_sets(served.sets, ease),
        reps_min=reps_min,
        reps_max=served.reps_max,
        seconds=seconds,
        weight_kg=weight,
    )

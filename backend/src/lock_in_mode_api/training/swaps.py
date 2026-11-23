"""Choosing a replacement exercise (ADR 0020, KB section 11). Pure: no database.

"This hurts, swap it" and "show another" both pick from the same safe list the plan uses
(the Picker: kit they own, no caution, nothing swapped out), for the same job:

- the same movement slot (a squat for a squat, a rear-shoulder move for a rear-shoulder
  move; warm-up for warm-up),
- the same kind of target (holds for holds, reps for reps), so the numbers still make sense,
- never more impact (no jumping where there was none),
- not already in this workout.
"""

from collections.abc import Collection

from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import IMPACT_ORDER, ExerciseInfo


def _fits(candidate: ExerciseInfo, current: ExerciseInfo, used: Collection[str]) -> bool:
    return (
        candidate.slug != current.slug
        and candidate.slug not in used
        and candidate.movement_slot == current.movement_slot
        and candidate.is_timed == current.is_timed
        and IMPACT_ORDER[candidate.impact] <= IMPACT_ORDER[current.impact]
    )


def _options(picker: Picker, current: ExerciseInfo, used: Collection[str]) -> list[ExerciseInfo]:
    return [c for c in picker.by_movement.get(current.movement_slot, []) if _fits(c, current, used)]


def _plan_order(picker: Picker, exercise: ExerciseInfo) -> tuple[object, ...]:
    """The order the plan itself would prefer: right for this user, then most effective."""
    misfit = picker.misfit(exercise)
    return (misfit > 0, misfit, -(exercise.effectiveness or 0), exercise.difficulty, exercise.slug)


def replacement(
    picker: Picker, painful: ExerciseInfo, used: Collection[str]
) -> ExerciseInfo | None:
    """The best stand-in for an exercise that hurt. None: nothing safe is left.

    Same or easier first (it just hurt), then right for this user's level or rung, then
    the same main muscle, then the closest difficulty, then the plan's own preference.
    """
    return min(
        _options(picker, painful, used),
        key=lambda c: (
            c.difficulty > painful.difficulty,
            picker.misfit(c) > 0,
            c.primary_muscle != painful.primary_muscle,
            abs(c.difficulty - painful.difficulty),
            *_plan_order(picker, c),
        ),
        default=None,
    )


def another(picker: Picker, current: ExerciseInfo, used: Collection[str]) -> ExerciseInfo | None:
    """ "Show another": the next option after the current one, in a fixed order, so tapping
    again walks through every option instead of bouncing between two. None: no other.
    """
    options = _options(picker, current, used)
    if not options:
        return None
    ordered = sorted([*options, current], key=lambda c: _plan_order(picker, c))
    at = ordered.index(current)
    return (ordered[at + 1 :] + ordered[:at])[0]

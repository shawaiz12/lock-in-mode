"""Moving up a level (ADR 0022, KB section 10). Pure: no database.

A beginner is offered "some experience" by either route:

- **12 good weeks**: 7-day stretches, counted from the first trained workout, with at
  least 2 trained workouts each. In total, not in a row: a week off pauses the count.
- **The three marks**, from any set ever logged: 15 push-ups, 25 bodyweight squats, a
  45 s plank. A harder move further up the same ladder counts too.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from lock_in_mode_api.models.enums import FitnessLevel, SessionKind
from lock_in_mode_api.training.plan_types import PlannedExercise, Workout

GOOD_WEEK_WORKOUTS = 2
GOOD_WEEKS_NEEDED = 12
WEEK_DAYS = 7


class LevelUpReason(StrEnum):
    GOOD_WEEKS = "good_weeks"  # 12 weeks with 2+ workouts
    STRENGTH_MARKS = "strength_marks"  # 15 push-ups, 25 squats, a 45 s plank


@dataclass(frozen=True)
class Mark:
    """One of the three: this move (or a harder one on its ladder) for this many."""

    slug: str
    reps: int | None = None
    seconds: int | None = None


MARKS = (
    Mark("push-up", reps=15),
    Mark("bodyweight-squat", reps=25),
    Mark("plank", seconds=45),
)


@dataclass(frozen=True)
class WeekShape:
    """One build-up week of a plan, as the "Ready for more?" screen describes it."""

    hard_workouts: int  # strength work or HIIT
    sets: int  # strength sets in the main blocks


def week_shape(week: Sequence[Workout]) -> WeekShape:
    hard = [w for w in week if w.kind == SessionKind.HIIT or any(_strength(e) for e in w.exercises)]
    sets = sum(e.sets for w in week for e in w.exercises if _strength(e))
    return WeekShape(len(hard), sets)


def _strength(exercise: PlannedExercise) -> bool:
    return exercise.reps_in_reserve is not None


def what_changes(
    now: WeekShape, next_level: WeekShape, *, minutes: int | None, low_intensity: bool
) -> list[str]:
    """What moving up changes, worked out from the next week built both ways: plain
    lines that are true for this user (no promise of "more" when time caps it)."""
    lines = []
    if next_level.hard_workouts != now.hard_workouts:
        lines.append(f"Hard workouts a week: {now.hard_workouts} → {next_level.hard_workouts}.")
    if next_level.sets > now.sets:
        lines.append(f"Sets a week: about {now.sets} → {next_level.sets}.")
    elif minutes is not None:
        lines.append(
            f"Your sessions stay {minutes} minutes, so the work gets harder rather than longer."
        )
    lines.append("Harder moves can be picked for you as you're ready for them.")
    if low_intensity:
        lines.append(
            "Your safety limits stay: no HIIT, no finishers, and 3 hard workouts a week at most."
        )
    lines.append("Your progress stays: the same weights, reps and moves you've reached.")
    return lines


@dataclass(frozen=True)
class Best:
    """The most reps and the longest hold ever logged in one set, per exercise slug."""

    reps: Mapping[str, int]
    seconds: Mapping[str, int]


def good_weeks(trained_at: Iterable[datetime]) -> int:
    """7-day stretches from the first trained workout with at least 2 trained workouts."""
    times = sorted(trained_at)
    if not times:
        return 0
    first = times[0]
    per_week = Counter((t - first).days // WEEK_DAYS for t in times)
    return sum(1 for count in per_week.values() if count >= GOOD_WEEK_WORKOUTS)


def ladder(slug: str, harder: Mapping[str, str | None]) -> list[str]:
    """This move and every harder one above it, following the library's `harder` links."""
    moves = [slug]
    step = harder.get(slug)
    while step is not None and step not in moves:
        moves.append(step)
        step = harder.get(step)
    return moves


def passes(
    mark: Mark, best: Best, harder: Mapping[str, str | None], timed: Mapping[str, bool]
) -> bool:
    """Has any logged set of this move, or a harder one, reached the mark? Holds count only
    on timed moves, reps only on moves done for reps."""
    for slug in ladder(mark.slug, harder):
        is_timed = timed.get(slug, False)
        if mark.reps is not None and not is_timed and best.reps.get(slug, 0) >= mark.reps:
            return True
        if mark.seconds is not None and is_timed and best.seconds.get(slug, 0) >= mark.seconds:
            return True
    return False


def passes_all(best: Best, harder: Mapping[str, str | None], timed: Mapping[str, bool]) -> bool:
    return all(passes(mark, best, harder, timed) for mark in MARKS)


def offer(level: FitnessLevel, weeks: int, marks: bool) -> LevelUpReason | None:
    """Why a beginner is offered "some experience", or None. Nobody else is, for now."""
    if level != FitnessLevel.BEGINNER:
        return None
    if marks:
        return LevelUpReason.STRENGTH_MARKS
    if weeks >= GOOD_WEEKS_NEEDED:
        return LevelUpReason.GOOD_WEEKS
    return None

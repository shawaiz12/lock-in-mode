"""Stage 2b: warm-ups, cool-downs, finishers and the cardio sessions (ADR 0016).

KB section 7 (HIIT and cardio) and section 8 (warm-up and cool-down). Every move is
offered through the Picker, so nothing the user can't do or was warned about appears.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lock_in_mode_api.models.enums import FitnessLevel, MuscleGroup, SessionKind
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import (
    ALLOWED_IMPACT,
    IMPACT_ORDER,
    ExerciseInfo,
    PlannedExercise,
)

S = SessionKind
G = MuscleGroup

# --- named move lists (KB sections 7 and 8). A test checks every slug exists. ---------

PULSE_RAISERS = ("march-in-place", "step-jacks", "low-impact-high-knees", "jumping-jacks")
JOINT_PREP = {
    "upper": ("arm-circles", "cat-cow", "thoracic-rotation"),
    "lower": ("leg-swings", "hip-circles", "ankle-rocks"),
    "full": ("world-s-greatest-stretch", "arm-circles", "leg-swings"),
}
STRETCHES = (
    "doorway-chest-stretch",
    "lat-stretch",
    "child-s-pose",
    "quad-stretch",
    "hip-flexor-stretch",
    "hamstring-stretch",
    "figure-four-glute-stretch",
    "calf-stretch",
)
# Which stretch helps a muscle that was trained. Arms and shoulders use chest and back.
STRETCH_FOR: dict[MuscleGroup, tuple[MuscleGroup, ...]] = {
    G.CHEST: (G.CHEST,),
    G.SHOULDERS: (G.CHEST, G.BACK),
    G.TRICEPS: (G.BACK,),
    G.BICEPS: (G.CHEST,),
    G.BACK: (G.BACK,),
    G.TRAPS: (G.BACK,),
    G.QUADS: (G.QUADS,),
    G.HAMSTRINGS: (G.HAMSTRINGS,),
    G.GLUTES: (G.GLUTES,),
    G.ADDUCTORS: (G.GLUTES,),
    G.CALVES: (G.CALVES,),
    G.CORE: (G.BACK,),
}
UPPER_MUSCLES = frozenset({G.CHEST, G.BACK, G.SHOULDERS, G.BICEPS, G.TRICEPS, G.TRAPS, G.FOREARMS})
LOWER_MUSCLES = frozenset({G.QUADS, G.HAMSTRINGS, G.GLUTES, G.CALVES, G.ADDUCTORS})

# HIIT: 4 to 6 moves rotating body areas so nothing gives out early (KB section 7).
HIIT_GROUPS: dict[str, tuple[str, ...]] = {
    "lower": ("bodyweight-squat", "squat-to-reach", "reverse-lunge", "jump-squat", "jump-lunge"),
    "cardio": (
        "jumping-jacks",
        "step-jacks",
        "high-knees",
        "low-impact-high-knees",
        "skater-hops",
        "side-steps",
    ),
    "push": ("push-up", "knee-push-up", "incline-push-up", "decline-push-up", "wall-push-up"),
    "core": (
        "mountain-climbers",
        "slow-mountain-climbers",
        "plank-shoulder-taps",
        "bear-crawl-hold",
    ),
    "full_body": ("squat-thrust", "burpee", "shadow-boxing", "inchworm", "tuck-jump"),
}
FINISHER_MOVES = HIIT_GROUPS["cardio"] + HIIT_GROUPS["full_body"]
STEADY_MOVES = (
    "brisk-walk",
    "jog",
    "cycling",
    "exercise-bike",
    "elliptical",
    "stair-climber",
    "rowing-machine",
    "stair-climbing",
)
EASY_MOVES = ("brisk-walk", "cycling", "exercise-bike", "elliptical")
MOBILITY_FLOW = (
    "cat-cow",
    "world-s-greatest-stretch",
    "thoracic-rotation",
    "hip-circles",
    "leg-swings",
    "arm-circles",
    "ankle-rocks",
    "child-s-pose",
    "hip-flexor-stretch",
    "hamstring-stretch",
    "figure-four-glute-stretch",
    "lat-stretch",
)
COOL_DOWN_WALK = "brisk-walk"


@dataclass(frozen=True)
class Intervals:
    work: int
    rest: int
    block_minutes: int  # longest HIIT block for the level
    effort: int  # 1-10, talk test


# KB section 7: work / rest, work block and effort by level.
INTERVALS = {
    FitnessLevel.BEGINNER: Intervals(20, 40, 10, 7),
    FitnessLevel.SOME_EXPERIENCE: Intervals(30, 30, 16, 8),
    FitnessLevel.EXPERIENCED: Intervals(40, 20, 20, 9),
}
STRETCH_SECONDS = 30
JOINT_PREP_SECONDS = 30
PRACTICE_SET_SECONDS = 70  # ~40 s of easy work and ~30 s to set up the real weight
STEADY_EFFORT, EASY_EFFORT, LONG_EFFORT, MOBILITY_EFFORT = 5, 3, 4, 2


def _timed(
    exercise: ExerciseInfo,
    seconds: int,
    *,
    sets: int = 1,
    rest: int = 0,
    effort: int | None = None,
    group: int = 0,
) -> PlannedExercise:
    return PlannedExercise(
        slug=exercise.slug,
        name=exercise.name,
        movement=exercise.movement_slot,
        sets=sets,
        reps_min=None,
        reps_max=None,
        seconds=seconds,
        rest_seconds=rest,
        reps_in_reserve=None,
        group=group,
        effort=effort,
    )


def _impact_ok(picker: Picker) -> set[str]:
    """Slugs whose impact suits the level (low only for beginners, KB section 7)."""
    allowed = ALLOWED_IMPACT[picker.answers.level]
    return {e.slug for e in picker.usable if e.impact in allowed}


def _intensity_rank(picker: Picker) -> Callable[[ExerciseInfo], tuple[object, ...]]:
    """Hardest move the level allows first: higher impact, then harder, then the name."""

    def rank(exercise: ExerciseInfo) -> tuple[object, ...]:
        over = exercise.difficulty > picker.cap
        return (over, -IMPACT_ORDER[exercise.impact], -exercise.difficulty, exercise.slug)

    return rank


# --- warm-up and cool-down (KB section 8) ------------------------------------------------


def _region(muscles: Sequence[MuscleGroup | None]) -> str:
    trained = {m for m in muscles if m is not None and m != G.CORE}
    if trained and trained <= UPPER_MUSCLES:
        return "upper"
    if trained and trained <= LOWER_MUSCLES:
        return "lower"
    return "full"


def warm_up(
    picker: Picker, budget_seconds: int, main_muscles: Sequence[MuscleGroup | None]
) -> list[PlannedExercise]:
    """Raise the pulse, loosen today's joints. Practice sets are added by the caller."""
    pulse_seconds = 60 if budget_seconds <= 180 else 90 if budget_seconds <= 300 else 120
    joint_moves = 1 if budget_seconds <= 120 else 2
    allowed = _impact_ok(picker)
    used: set[str] = set()
    moves: list[PlannedExercise] = []
    pulse = picker.from_list("warm:pulse", [s for s in PULSE_RAISERS if s in allowed], used, size=2)
    if pulse is not None:
        used.add(pulse.slug)
        moves.append(_timed(pulse, pulse_seconds, effort=3))
    for slug in JOINT_PREP[_region(main_muscles)]:
        if len(moves) > joint_moves:
            break
        exercise = picker.by_slug.get(slug)
        if exercise is not None and slug not in used:
            used.add(slug)
            moves.append(_timed(exercise, JOINT_PREP_SECONDS, effort=2))
    return moves


def warm_up_seconds(moves: Sequence[PlannedExercise]) -> int:
    return sum((m.seconds or 0) * m.sets for m in moves)


def cool_down(
    picker: Picker, budget_seconds: int, main_muscles: Sequence[MuscleGroup | None]
) -> list[PlannedExercise]:
    """Slow down with an easy walk, then hold stretches for what was trained."""
    walk_seconds = 30 if budget_seconds <= 60 else 60
    count = max(1, min(4, (budget_seconds - walk_seconds) // STRETCH_SECONDS))
    need: Counter[MuscleGroup] = Counter()
    for muscle in main_muscles:
        for stretched in STRETCH_FOR.get(muscle, ()) if muscle is not None else ():
            need[stretched] += 1
    stretches = [picker.by_slug[s] for s in STRETCHES if s in picker.by_slug]
    useful = [e for e in stretches if e.primary_muscle is not None and need[e.primary_muscle]]
    if useful:  # only stretch what was trained; a short cool-down beats a padded one
        stretches = useful
    stretches.sort(key=lambda e: (-need[e.primary_muscle] if e.primary_muscle else 0, e.slug))
    moves: list[PlannedExercise] = []
    walk = picker.by_slug.get(COOL_DOWN_WALK)
    if walk is not None:
        moves.append(_timed(walk, walk_seconds, effort=2))
    moves += [_timed(e, STRETCH_SECONDS, effort=MOBILITY_EFFORT) for e in stretches[:count]]
    return moves


# --- finisher (lose fat, 2-3 days; KB section 7) ------------------------------------------

FINISHER_MINUTES = {20: 4, 30: 5, 45: 6, 60: 8, 75: 8, 90: 8}
NO_LIMIT_FINISHER_MINUTES = 8


def finisher_minutes(minutes: int | None) -> int:
    return NO_LIMIT_FINISHER_MINUTES if minutes is None else FINISHER_MINUTES.get(minutes, 0)


def finisher(picker: Picker, minutes: int) -> list[PlannedExercise]:
    """Two moves taking turns in short intervals, gentle for beginners."""
    timing = INTERVALS[picker.answers.level]
    rounds = (minutes * 60) // (timing.work + timing.rest)
    allowed = _impact_ok(picker)
    options = [s for s in FINISHER_MOVES if s in allowed]
    used: set[str] = set()
    moves: list[PlannedExercise] = []
    rank = _intensity_rank(picker)
    for index in range(2):
        move = picker.from_list("finisher", options, used, rank=rank)
        if move is None:
            break
        used.add(move.slug)
        share = rounds // 2 + (rounds % 2 if index == 0 else 0)
        moves.append(_timed(move, timing.work, sets=share, rest=timing.rest, effort=timing.effort))
    return moves


# --- cardio sessions ------------------------------------------------------------------


def hiit(picker: Picker, main_budget_seconds: int | None) -> list[PlannedExercise]:
    """One move from each body area, repeated in rounds (KB section 7)."""
    timing = INTERVALS[picker.answers.level]
    allowed = _impact_ok(picker)
    rank = _intensity_rank(picker)
    used: set[str] = set()
    moves: list[ExerciseInfo] = []
    for area, slugs in HIIT_GROUPS.items():
        move = picker.from_list(
            f"hiit:{area}",
            [s for s in slugs if s in allowed],
            used,
            rank=rank,
        )
        if move is not None:
            used.add(move.slug)
            moves.append(move)
    round_seconds = len(moves) * (timing.work + timing.rest)
    block = timing.block_minutes * 60
    if main_budget_seconds is not None:
        block = min(block, main_budget_seconds)
    rounds = max(1, block // round_seconds) if round_seconds else 0
    return [
        _timed(m, timing.work, sets=rounds, rest=timing.rest, effort=timing.effort) for m in moves
    ]


def steady(
    picker: Picker, kind: SessionKind, main_budget_seconds: int | None
) -> list[PlannedExercise]:
    """One continuous activity at talking pace: steady, long or easy (KB section 7)."""
    allowed = _impact_ok(picker)
    slugs: Sequence[str]
    if kind == S.EASY_CARDIO:
        slugs, effort, default_minutes = EASY_MOVES, EASY_EFFORT, 20
    elif kind == S.LONG_CARDIO:
        slugs, effort, default_minutes = STEADY_MOVES, LONG_EFFORT, 45
    else:
        slugs, effort, default_minutes = STEADY_MOVES, STEADY_EFFORT, 30
    # Walking first: everyone can do it, anywhere. Machines rotate in for gym users.
    move = picker.from_list(f"cardio:{kind.value}", [s for s in slugs if s in allowed], set())
    if move is None:
        return []
    seconds = default_minutes * 60
    if main_budget_seconds is not None:
        seconds = main_budget_seconds
    return [_timed(move, seconds, effort=effort)]


def mobility(picker: Picker, main_budget_seconds: int | None) -> list[PlannedExercise]:
    """A gentle flow of joint moves and stretches, 40 s each (12 minutes at most)."""
    seconds = min(main_budget_seconds or 12 * 60, 12 * 60)
    flow = [picker.by_slug[s] for s in MOBILITY_FLOW if s in picker.by_slug]
    count = max(1, seconds // 40)
    return [_timed(e, 40, effort=MOBILITY_EFFORT) for e in flow[:count]]

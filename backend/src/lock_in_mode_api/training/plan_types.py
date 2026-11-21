"""Shared shapes and numbers for the plan generator (ADR 0014, 0015, 0016)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from lock_in_mode_api.models.enums import (
    Equipment,
    ExerciseType,
    FitnessLevel,
    Impact,
    MovementSlot,
    MuscleGroup,
    SessionKind,
    WorkoutFormat,
)
from lock_in_mode_api.training.exercise_rules import ExerciseFacts, UserSetup
from lock_in_mode_api.training.routine import PlanInputs

S = SessionKind

# Session length → (warm-up, main block, cool-down) minutes (KB section 9; 75/90 extend it).
SESSION_SPLIT: dict[int, tuple[int, int, int]] = {
    10: (2, 7, 1),
    20: (3, 15, 2),
    30: (4, 23, 3),
    45: (5, 36, 4),
    60: (5, 50, 5),
    75: (6, 63, 6),
    90: (7, 76, 7),
}
NO_LIMIT_SPLIT = (5, None, 5)  # "no limit": full warm-up and cool-down, main block unbounded
MAIN_BLOCK_MINUTES = {minutes: split[1] for minutes, split in SESSION_SPLIT.items()}

# Hardest rung a level starts on (difficulty 1-5). The first workout corrects it.
LEVEL_MAX_DIFFICULTY = {
    FitnessLevel.BEGINNER: 2,
    FitnessLevel.SOME_EXPERIENCE: 4,
    FitnessLevel.EXPERIENCED: 5,
}
# Jumping allowed in HIIT, finishers and cardio by level (KB section 7).
ALLOWED_IMPACT = {
    FitnessLevel.BEGINNER: frozenset({Impact.NONE, Impact.LOW}),
    FitnessLevel.SOME_EXPERIENCE: frozenset({Impact.NONE, Impact.LOW, Impact.MEDIUM}),
    FitnessLevel.EXPERIENCED: frozenset(Impact),
}
IMPACT_ORDER = {Impact.NONE: 0, Impact.LOW: 1, Impact.MEDIUM: 2, Impact.HIGH: 3}
WEIGHTED_KIT = frozenset({Equipment.DUMBBELLS, Equipment.GYM})

TITLES = {
    S.FULL_BODY: "Full body",
    S.UPPER: "Upper body",
    S.LOWER: "Lower body",
    S.PUSH: "Push",
    S.PULL: "Pull",
    S.LEGS: "Legs",
    S.BRO_CHEST: "Chest",
    S.BRO_BACK: "Back",
    S.BRO_LEGS: "Legs",
    S.BRO_SHOULDERS: "Shoulders",
    S.BRO_ARMS: "Arms and core",
    S.CIRCUIT: "Circuit",
    S.HIIT: "HIIT",
    S.STEADY_CARDIO: "Steady cardio",
    S.LONG_CARDIO: "Long easy cardio",
    S.EASY_CARDIO: "Easy walk",
    S.MOBILITY: "Mobility",
}


class ExerciseInfo(ExerciseFacts, Protocol):
    """What the builder reads from an exercise. Seed entries and database rows both fit."""

    @property
    def slug(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def movement_slot(self) -> MovementSlot: ...
    @property
    def exercise_type(self) -> ExerciseType: ...
    @property
    def targets(self) -> Sequence[str]: ...
    @property
    def difficulty(self) -> int: ...
    @property
    def effectiveness(self) -> int | None: ...
    @property
    def is_timed(self) -> bool: ...
    @property
    def primary_muscle(self) -> MuscleGroup | None: ...


class BuildInputs(PlanInputs, UserSetup, Protocol):
    """Every answer the builder reads. Profile rows fit."""


def is_weighted(exercise: ExerciseInfo) -> bool:
    return bool(WEIGHTED_KIT & set(exercise.equipment))


@dataclass(frozen=True)
class PlannedExercise:
    slug: str
    name: str
    movement: MovementSlot
    sets: int  # rounds, for circuits and intervals
    reps_min: int | None  # None for timed moves and open test sets
    reps_max: int | None
    seconds: int | None  # timed moves: hold or work this long
    rest_seconds: int  # after each set (circuit and intervals: before the next move)
    reps_in_reserve: int | None  # "stop when you could still do this many more good reps"
    group: int = 0  # exercises with the same group are done back to back
    rest_floor: int = 0  # shortest rest the goal allows, used when time is tight
    effort: int | None = None  # cardio: 1-10 talk-test effort (KB section 7)
    practice_sets: int = 0  # warm-up sets before this exercise (KB section 8)
    test: bool = False  # first workout: open target, places the user on the ladder


@dataclass(frozen=True)
class Workout:
    kind: SessionKind
    letter: str  # "A", "B", "C" for rotating templates; "" otherwise
    title: str
    format: WorkoutFormat
    exercises: tuple[PlannedExercise, ...]  # the main block
    main_minutes: int  # estimated main block (finisher included)
    warm_up: tuple[PlannedExercise, ...] = ()
    finisher: tuple[PlannedExercise, ...] = ()
    cool_down: tuple[PlannedExercise, ...] = ()
    total_minutes: int = 0  # warm-up + main + finisher + cool-down, rounded up

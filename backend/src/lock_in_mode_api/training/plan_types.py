"""Shared shapes and numbers for the plan generator (ADR 0014, 0015, 0016, 0017)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, Self

from lock_in_mode_api.models.enums import (
    Equipment,
    ExerciseType,
    FitnessLevel,
    Goal,
    Impact,
    Location,
    MovementSlot,
    MuscleGroup,
    SessionKind,
    ShoulderDay,
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

# A training block (ADR 0017): build-up weeks, then a recovery week. Same for every level.
BUILD_WEEKS = 4
RECOVERY_WEEKS = 1
BLOCK_WEEKS = BUILD_WEEKS + RECOVERY_WEEKS
# Recovery week (KB section 10): same exercises, half the sets, stop 4 reps short.
RECOVERY_REPS_IN_RESERVE = 4
RECOVERY_EFFORT_DROP = 2  # intervals: 2 points easier on the 1-10 talk test
RECOVERY_MIN_EFFORT = 3

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


@dataclass(frozen=True)
class PlanAnswers:
    """Exactly the answers a plan is built from: every field the generator reads.

    Saved with each plan (ADR 0017). When the profile's version differs, the plan is out
    of date and a new block starts. Obstacles and the name are left out: they never
    change the plan.
    """

    goal: Goal
    level: FitnessLevel
    location: Location
    equipment: tuple[str, ...]
    limits: tuple[str, ...]
    days_per_week: int
    minutes_per_session: int | None
    women_home_track: bool
    prefers_bro_split: bool
    shoulder_day: ShoulderDay
    needs_low_intensity: bool

    @classmethod
    def of(cls, source: BuildInputs) -> Self:
        return cls(
            goal=source.goal,
            level=source.level,
            location=source.location,
            equipment=tuple(source.equipment),
            limits=tuple(source.limits),
            days_per_week=source.days_per_week,
            minutes_per_session=source.minutes_per_session,
            women_home_track=source.women_home_track,
            prefers_bro_split=source.prefers_bro_split,
            shoulder_day=source.shoulder_day,
            needs_low_intensity=source.needs_low_intensity,
        )

    def to_json(self) -> dict[str, Any]:
        """Plain JSON values (enum text, lists), as stored in plans.generated_from."""
        return {
            "goal": self.goal.value,
            "level": self.level.value,
            "location": self.location.value,
            "equipment": list(self.equipment),
            "limits": list(self.limits),
            "days_per_week": self.days_per_week,
            "minutes_per_session": self.minutes_per_session,
            "women_home_track": self.women_home_track,
            "prefers_bro_split": self.prefers_bro_split,
            "shoulder_day": self.shoulder_day.value,
            "needs_low_intensity": self.needs_low_intensity,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            goal=Goal(data["goal"]),
            level=FitnessLevel(data["level"]),
            location=Location(data["location"]),
            equipment=tuple(data["equipment"]),
            limits=tuple(data["limits"]),
            days_per_week=data["days_per_week"],
            minutes_per_session=data["minutes_per_session"],
            women_home_track=data["women_home_track"],
            prefers_bro_split=data["prefers_bro_split"],
            shoulder_day=ShoulderDay(data["shoulder_day"]),
            needs_low_intensity=data["needs_low_intensity"],
        )


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
    recovery: bool = False  # the block's lighter week (ADR 0017)

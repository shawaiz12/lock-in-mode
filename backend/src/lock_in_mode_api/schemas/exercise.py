"""Exercise library in and out (ADR 0013)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from lock_in_mode_api.models.enums import (
    BodyLimit,
    Caution,
    Equipment,
    ExerciseCategory,
    ExerciseType,
    Impact,
    MovementSlot,
    MuscleGroup,
    MuscleHead,
)

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100


class ExerciseFilters(BaseModel):
    """Query parameters for GET /exercises. Unknown parameters are an error (catches typos)."""

    model_config = ConfigDict(extra="forbid")

    for_me: bool = Field(
        default=False,
        description="Only exercises this user's equipment and location allow. Needs a profile.",
    )
    category: ExerciseCategory | None = None
    movement_slot: MovementSlot | None = None
    muscle: MuscleGroup | None = Field(default=None, description="Primary or secondary muscle.")
    max_difficulty: int | None = Field(default=None, ge=1, le=5)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX)


class ExerciseRef(BaseModel):
    """A link to another exercise (easier / harder / alternative)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    difficulty: int


class ExerciseSummary(BaseModel):
    """One row in the library list: enough to show a card."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    category: ExerciseCategory
    movement_slot: MovementSlot
    primary_muscle: MuscleGroup | None
    equipment: list[Equipment]
    also_needs: str | None
    difficulty: int
    impact: Impact
    is_timed: bool
    demo_url: str | None
    cautions: list[Caution] = Field(
        default_factory=list,
        description="Why this may not suit the user (body limits, safety result, quiet track). "
        "Empty without a profile. Show a warning; the plan generator never picks these.",
    )


class ExerciseDetail(ExerciseSummary):
    """Everything the workout player and the exercise screen need."""

    exercise_type: ExerciseType
    secondary_muscles: list[MuscleGroup]
    targets: list[MuscleHead]
    not_suitable_for: list[BodyLimit]
    steps: list[str]
    cues: list[str]
    common_mistake: str | None
    easier: ExerciseRef | None
    harder: ExerciseRef | None
    alternatives: list[ExerciseRef]


class ExercisePage(BaseModel):
    items: list[ExerciseSummary]
    page: int
    page_size: int
    total: int = Field(description="Exercises matching the filters, across all pages.")

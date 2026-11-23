"""Plans and workouts out (ADR 0017). Nothing comes in: plans are built from the profile."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from lock_in_mode_api.models.enums import (
    RoutineKind,
    SessionKind,
    WorkoutFormat,
    WorkoutStatus,
)
from lock_in_mode_api.schemas.exercise import ExerciseRef


class LastResult(BaseModel):
    """The last set logged for this exercise, in any workout: pre-fill the next set with it."""

    reps: int | None
    weight_kg: float | None
    seconds: int | None
    logged_at: datetime


class PlannedExerciseRead(BaseModel):
    """One exercise with the numbers to hit. `null` fields don't apply to this move."""

    id: uuid.UUID = Field(description="Log sets against this id (PUT /sessions/.../sets).")
    exercise: ExerciseRef
    sets: int = Field(description="Rounds, for circuits and intervals.")
    reps_min: int | None = Field(description="null: timed move, or an open test set.")
    reps_max: int | None
    seconds: int | None = Field(description="Timed moves: hold or work this long.")
    rest_seconds: int = Field(description="After each set (circuits: before the next move).")
    reps_in_reserve: int | None = Field(
        description='Strength: "stop when you could still do this many more good reps".'
    )
    effort: int | None = Field(description="Cardio: 1-10 on the talk test.")
    group: int = Field(description="Same number: done back to back (supersets, circuits).")
    practice_sets: int = Field(description="Light warm-up sets before the first real set.")
    is_test: bool = Field(
        description="First-workout strength test: as many good reps as you can, stop with "
        "2 left (bodyweight), or pick a weight you can lift with 3 left (weights)."
    )
    swapped_out: bool = Field(
        description="Swapped mid-workout (ADR 0020): its logged sets stay here, the next "
        "exercise replaces it. Show it as done/greyed."
    )
    weight_kg: float | None = Field(
        description="Suggested weight for every set: their progress (ADR 0019), else the "
        "last weight they logged. null: no weight involved yet, or let them pick."
    )
    last: LastResult | None = Field(description="null until this exercise is first logged.")


class WorkoutSummary(BaseModel):
    """One workout in the queue, enough for a list or the home screen card."""

    id: uuid.UUID
    position: int = Field(description="Queue order across the whole block, from 1.")
    week: int
    kind: SessionKind
    title: str
    format: WorkoutFormat
    recovery: bool = Field(description="Part of the block's lighter week.")
    total_minutes: int
    status: WorkoutStatus
    comeback_week: int | None = Field(
        description="Back after a break (ADR 0021): the comeback week this workout is eased "
        "for, from 1. Its numbers are already lighter. null: not eased."
    )


class WorkoutDetail(WorkoutSummary):
    """Everything the workout player needs, in the order it's done."""

    plan_id: uuid.UUID
    main_minutes: int
    warm_up: list[PlannedExerciseRead]
    main: list[PlannedExerciseRead]
    finisher: list[PlannedExerciseRead]
    cool_down: list[PlannedExerciseRead]


class ComebackRead(BaseModel):
    """Back after a break of 14+ days (ADR 0021). The next workouts are served lighter;
    the user's saved progress is untouched and applies again once it's over."""

    away_days: int = Field(description="Whole days since the last ticked set.")
    weeks: int = Field(description="1: one easy week (14-28 days away). 3: a ramp back up.")
    week: int = Field(description="The comeback week the next workout is in, from 1.")
    workouts_left: int = Field(description="Eased workouts still to train.")
    started: bool = Field(
        description='false until the first workout back is started: show "Welcome back" '
        "(never how long they were gone). Either way, DELETE /me/comeback ends it "
        '("I kept training elsewhere").'
    )


class PlanRead(BaseModel):
    """The current block: the plan reveal screen and the queue."""

    id: uuid.UUID
    block_number: int
    routine_kind: RoutineKind
    reasons: list[str] = Field(description="Plain-language 'why' lines for the reveal screen.")
    weekdays: list[int] = Field(
        description="Suggested day for each session of a week, in queue order. 0 = Monday. "
        "Only a suggestion: the queue never marks anything missed."
    )
    uses_push_pull_legs: bool
    weeks: int = Field(description="Build-up weeks plus the recovery week.")
    created_at: datetime
    next_workout_id: uuid.UUID | None = Field(description="null when the block is complete.")
    block_complete: bool = Field(
        description='Every workout done or skipped: show "Block complete!" and offer '
        "POST /plans for the next block."
    )
    comeback: ComebackRead | None = Field(description="null: no break to come back from.")
    workouts: list[WorkoutSummary]

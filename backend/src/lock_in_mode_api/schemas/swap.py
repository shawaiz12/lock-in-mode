"""Swapping exercises: "this hurts, swap it" and "show another" (ADR 0020)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from lock_in_mode_api.models.enums import BodyArea, BodyLimit, SwapReason
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.plan import WorkoutDetail


class SwapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: uuid.UUID = Field(
        description="The exercise on screen. If the row holds a different one now (a double "
        "tap already swapped it), nothing changes: 409 exercise_changed."
    )
    reason: SwapReason = Field(
        description="hurts: gone for good (undo in /me/swapped-out). another: today only."
    )


class SwapResult(BaseModel):
    """Today's workout after the swap, and what changed."""

    workout: WorkoutDetail
    swapped_out: ExerciseRef
    swapped_in: ExerciseRef | None = Field(
        description="The replacement. null: nothing safe was left (see left_out), or every "
        "set of it was already done."
    )
    left_out: bool = Field(
        description='Nothing safe is left for this slot: "Nothing else safe for this one, so '
        "we've left it out.\""
    )


class SwappedOutRead(BaseModel):
    """One exercise the user swapped out because it hurt."""

    exercise: ExerciseRef
    body_area: BodyArea | None = Field(description="Where it hurt, if they said.")
    swapped_at: datetime


class WhereItHurts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_area: BodyArea


class WhereResult(SwappedOutRead):
    suggest_limit: BodyLimit | None = Field(
        description='Offer "Go easy on your knees in every workout?" AFTER the workout '
        "(changing the profile finishes an open workout and rebuilds the plan). Yes: add "
        "it to `limits` with PUT /me/profile. null: 'other', or it's already a limit."
    )

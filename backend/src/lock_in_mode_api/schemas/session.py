"""Doing a workout: start, tick sets, finish (ADR 0018).

A workout done offline (ADR 0033) reaches the API later: each call can say when it really
happened on the phone (`started_at`, `logged_at`, `finished_at`). The server checks
those times and keeps them in order; leave them out and the server's time is used.
"""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from lock_in_mode_api.models.enums import Feedback, MovementSlot, ProgressChange
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.user import SignInOffer


class SessionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workout_id: uuid.UUID = Field(description="The next workout (plans/current/next).")
    started_at: AwareDatetime | None = Field(
        default=None,
        description="When the phone started it, for a workout started offline (ADR 0033). "
        "Kept between the user's last workout and now. Ignored when continuing.",
    )


class SetLogWrite(BaseModel):
    """One ticked set. The app pre-fills it from the plan or the last result."""

    model_config = ConfigDict(extra="forbid")

    reps: int | None = Field(default=None, ge=0, le=1000)
    weight_kg: float | None = Field(default=None, ge=0, le=1000, description="Weighted moves.")
    seconds: int | None = Field(default=None, ge=0, le=10800, description="Timed moves.")
    logged_at: AwareDatetime | None = Field(
        default=None,
        description="When the phone ticked it (ADR 0033). Kept between the workout's start "
        "and now.",
    )

    @model_validator(mode="after")
    def _reps_or_seconds(self) -> Self:
        if self.reps is None and self.seconds is None:
            raise ValueError("Send reps, seconds, or both")
        return self


class SetLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    planned_exercise_id: uuid.UUID
    set_number: int
    reps: int | None
    weight_kg: float | None
    seconds: int | None


class SessionRead(BaseModel):
    """An open or finished session with every set logged so far."""

    id: uuid.UUID
    workout_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    feedback: Feedback | None
    sets: list[SetLogRead]


class SessionFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: Feedback | None = Field(
        default=None, description="Too easy / just right / too hard. Leave out to skip."
    )
    finished_at: AwareDatetime | None = Field(
        default=None,
        description="When the phone finished it (ADR 0033). Kept between the last ticked "
        "set and now.",
    )


class Placement(BaseModel):
    """What the strength test decided for one movement: "3 push-ups → knee push-ups"."""

    movement: MovementSlot
    result: int
    unit: Literal["reps", "seconds"]
    exercise: ExerciseRef = Field(description="The rung they start on.")


class Progress(BaseModel):
    """What changed for one exercise: "Goblet squat: 12 kg → 14.5 kg next time"."""

    exercise: ExerciseRef
    change: ProgressChange
    weight_kg: float | None = Field(description="The new suggested weight, if any.")
    seconds: int | None = Field(description="The new hold, if any.")
    set_change: int = Field(description="Sets compared with the plan: -1, 0 or +1.")


class IntervalProgress(BaseModel):
    """What moved the user's HIIT and finisher timing (ADR 0023):
    "Intervals up: 35 s on / 25 s off next time". Every round stays one minute."""

    direction: Literal["up", "down"]
    work_seconds: int = Field(description="Seconds of work per interval from now on.")
    rest_seconds: int = Field(description="Seconds of rest per interval from now on.")


class SessionResult(SessionRead):
    """The finished session, what the test placed (if it was the test), what moved up or
    back (ADR 0019 and 0023), and the queue."""

    placements: list[Placement]
    progress: list[Progress]
    intervals: IntervalProgress | None = Field(
        default=None, description="HIIT and finisher timing moved up or down (ADR 0023)."
    )
    recovery_earned: bool = Field(
        description="This finish brought the recovery week forward: show it as earned "
        "recovery, never as failing."
    )
    next_workout_id: uuid.UUID | None
    block_complete: bool
    sign_in_offer: SignInOffer | None = Field(
        default=None,
        description=(
            "Guests only, at their 3rd and 10th finished workout and their first finished "
            'block (ADR 0026): show "Protect your progress". null otherwise.'
        ),
    )

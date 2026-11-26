import uuid
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

type SignInMilestone = Literal["workout_3", "workout_10", "first_block"]


class ProgressSummary(BaseModel):
    """What a guest would lose (ADR 0026): "Your plan knows you: …". Real counts only."""

    workouts_finished: int
    sets_logged: int
    exercises_with_own_numbers: int = Field(
        description="Exercises whose weight, reps, sets or hold are saved for this user."
    )
    exercises_left_out: int = Field(
        description='Exercises taken out with "This hurts, swap it" and not put back.'
    )
    strength_test_moves: int = Field(
        description="Moves the strength test set a starting point for."
    )
    lines: list[str] = Field(
        description=(
            'Ready to show under "Your plan knows you", in this order: "7 workouts '
            'finished", "96 sets logged", "Your own numbers saved for 12 exercises", '
            '"2 exercises left out because they hurt", "Strength test: starting points '
            'for 4 moves". A count of 0 has no line.'
        )
    )


class SignInOffer(BaseModel):
    """On the finish screen (ADR 0026): show "Protect your progress" with Google/Apple
    sign-in (`POST /me/link/{google|apple}`) and "Not now" (no call needed)."""

    milestone: SignInMilestone = Field(
        description="Their 3rd or 10th finished workout, or their first finished block."
    )
    summary: ProgressSummary


class Reminder(BaseModel):
    """The training reminder (ADR 0034): local time on the phone and the days it rings."""

    at: time = Field(description='Local time, "18:30". Seconds are dropped.')
    days: list[int] = Field(
        min_length=1,
        max_length=7,
        description="Days it rings: 0 = Monday … 6 = Sunday, each once.",
    )

    @field_validator("at")
    @classmethod
    def _minutes(cls, at: time) -> time:
        return at.replace(second=0, microsecond=0, tzinfo=None)

    @field_validator("days")
    @classmethod
    def _days(cls, days: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in days) or len(set(days)) != len(days):
            raise ValueError("days are 0 (Monday) to 6 (Sunday), each once")
        return sorted(days)


def _known_zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"unknown time zone: {name}") from error
    return name


class UserRead(BaseModel):
    """Public view of a user. Never includes provider ids (google_sub/apple_sub)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_guest: bool
    display_name: str | None
    created_at: datetime
    share_usage_data: bool = Field(
        description='The "Share usage data" setting (ADR 0025). Off: no usage events.'
    )
    time_zone: str | None = Field(
        default=None, description="The phone's time zone (ADR 0034); null until sent."
    )
    reminder: Reminder | None = Field(
        default=None, description="The training reminder (ADR 0034); null: none."
    )
    progress_summary: ProgressSummary | None = Field(
        default=None,
        description=(
            'Guests only (ADR 0026): for a quiet "Protect your progress" card. Guest '
            "progress lives only on this phone. null for Google/Apple accounts."
        ),
    )


class UserUpdate(BaseModel):
    """PATCH /me: send only what changes. A field left out stays as it is."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="The optional name from the welcome screen; null clears it.",
    )
    share_usage_data: bool = Field(
        default=True,
        description=(
            '"Share usage data" (ADR 0025). false: stop recording usage events and erase '
            "the ones recorded so far. true: start again from now."
        ),
    )
    time_zone: str = Field(
        default="UTC",
        max_length=64,
        description='The phone\'s time zone, an IANA name like "Asia/Karachi" (ADR 0034). '
        "Weeks run Monday to Sunday there.",
    )
    reminder: Reminder | None = Field(
        default=None,
        description="Set or change the training reminder; null turns it off (ADR 0034).",
    )

    @field_validator("time_zone")
    @classmethod
    def _zone(cls, name: str) -> str:
        return _known_zone(name)


class AccountDeletion(BaseModel):
    """202 from `DELETE /me` for a Google/Apple account (ADR 0024)."""

    delete_after: datetime = Field(
        description=(
            "When the account and everything in it is erased. Show it as a date: "
            '"Deleted on 24 Dec. Sign in before then to cancel."'
        )
    )

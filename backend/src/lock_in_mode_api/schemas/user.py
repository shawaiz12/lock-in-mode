import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class AccountDeletion(BaseModel):
    """202 from `DELETE /me` for a Google/Apple account (ADR 0024)."""

    delete_after: datetime = Field(
        description=(
            "When the account and everything in it is erased. Show it as a date: "
            '"Deleted on 24 Dec. Sign in before then to cancel."'
        )
    )

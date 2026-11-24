import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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

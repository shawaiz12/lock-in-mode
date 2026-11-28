"""The waitlist's requests and answers (ADR 0037)."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from lock_in_mode_api.models.enums import TrainsAt


def _lower(value: str) -> str:
    return value.strip().lower()


class JoinWaitlist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, AfterValidator(_lower), Field(max_length=254)]
    trains_at: TrainsAt | None = None
    # From the share link (?r=CODE). A code nobody has is ignored, not an error: an old
    # link shouldn't stop a friend joining.
    ref: str | None = Field(default=None, max_length=16)
    # From the bio link (?s=tiktok). Anything that isn't a plain tag is dropped.
    source: str | None = Field(default=None, max_length=64)


class LeaveWaitlist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=20, max_length=100)


class CountVisit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(default=None, max_length=64)


class WaitlistSpot(BaseModel):
    """Someone's place in line, read by their link code."""

    referral_code: str
    position: int = Field(description="1 = first in line")
    friends_joined: int = Field(description="People who joined with this person's link")
    on_list: int = Field(description="Everyone on the waitlist right now")
    top_spots: int = Field(description="The top this many get an early Android invite")
    in_top: bool


class JoinedWaitlist(WaitlistSpot):
    """POST /waitlist. `key` comes once, to a new signup only: the page keeps it to leave
    the list later. Someone already on the list gets their spot without a key."""

    already_on_list: bool
    key: str | None = None


class WaitlistCount(BaseModel):
    """What the page may show. `count` is null below `waitlist_count_shown_from`, so the
    page never says "3 people locked in"."""

    count: int | None
    founding_discount_percent: int
    top_spots: int

"""The waitlist (ADR 0037): people who want the app before it exists.

waitlist_signups  one row per email. Not an app account and not linked to `users`: the
                  app has no emails yet (guests), so nothing here is deleted with an
                  account, and nothing about an account is kept here.
waitlist_visits   page views per day and source, so the report can say how many visitors
                  joined (the page's conversion rate). Counts only: no IPs, no cookies.

The line ("your spot") isn't stored: it's worked out on every read from referrals and
join times (services/waitlist.py), so it can never drift out of date.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import TrainsAt

# The link code people share: 8 characters from an alphabet with no look-alikes (no 0/O,
# 1/I/L), so it survives being read out or typed from a screenshot.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
# Where people came from (?s=tiktok on the bio link): short, lower-case, a-z 0-9 _ -.
SOURCE_PATTERN = r"^[a-z0-9_-]{1,32}$"


class WaitlistSignup(Base):
    __tablename__ = "waitlist_signups"
    __table_args__ = (
        CheckConstraint("email = lower(email) AND email = btrim(email)", name="email_normalised"),
        CheckConstraint(
            f"referral_code ~ '^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$'", name="referral_code_shape"
        ),
        CheckConstraint(f"source IS NULL OR source ~ '{SOURCE_PATTERN}'", name="source_shape"),
        CheckConstraint("referred_by_id IS NULL OR referred_by_id <> id", name="no_self_referral"),
        # "Whose friends are these?": the line counts them on every read.
        Index("ix_waitlist_signups_referred_by_id", "referred_by_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # Stored trimmed and lower-case (the CHECK makes sure), so "Ali@Gmail.com " and
    # "ali@gmail.com" are the same person and can't join twice.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    # Public: it's in the share link. Seeing someone's spot by their code is fine.
    referral_code: Mapped[str] = mapped_column(String(CODE_LENGTH), unique=True)
    # Private: the browser that joined keeps the key; only its sha256 is stored (like
    # refresh tokens, ADR 0005). The key is what lets someone leave the list, so a shared
    # link can never remove its owner.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Whose link brought them. The friend stays if the referrer leaves (SET NULL).
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("waitlist_signups.id", ondelete="SET NULL")
    )
    trains_at: Mapped[TrainsAt | None] = mapped_column(enum_column(TrainsAt))
    source: Mapped[str | None] = mapped_column(String(32))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class WaitlistVisit(Base):
    __tablename__ = "waitlist_visits"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    # "" = no source in the link (someone typed the address, or an untagged share).
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    visits: Mapped[int] = mapped_column(server_default="0")

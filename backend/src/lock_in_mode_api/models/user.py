import uuid
from datetime import datetime, time

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Time,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import LeavingReason


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # A leaving reason only while the account waits to be deleted (ADR 0024).
        CheckConstraint(
            "deletion_reason IS NULL OR delete_after IS NOT NULL", name="reason_only_when_leaving"
        ),
        # The hourly cleanup's lookup: only the few waiting accounts are in this index.
        Index(
            "ix_users_delete_after",
            "delete_after",
            postgresql_where=text("delete_after IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    apple_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_guest: Mapped[bool] = mapped_column(default=True, server_default=true())
    display_name: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set when a Google/Apple account asks to be deleted (ADR 0024): the account is
    # erased once this has passed (database clock). Signing in before then clears it.
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Their optional "Why are you leaving?", kept here until the account is really gone.
    deletion_reason: Mapped[LeavingReason | None] = mapped_column(enum_column(LeavingReason))

    # "Share usage data" (ADR 0025): off = no funnel events, and past ones are erased.
    share_usage_data: Mapped[bool] = mapped_column(default=True, server_default=true())

    # The phone's time zone, an IANA name like "Asia/Karachi" (ADR 0034): their week runs
    # Monday to Sunday there. NULL until the app first sends it: weeks are then in UTC.
    time_zone: Mapped[str | None] = mapped_column(String(64))
    # The training reminder (ADR 0034): the local time and the days (0 = Monday … 6 =
    # Sunday). Both set or both NULL (no reminder); kept together by services/profile.py.
    # The phone schedules it; it's kept here so a new phone can set it up again.
    reminder_at: Mapped[time | None] = mapped_column(Time)
    reminder_days: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))

    @property
    def reminder(self) -> dict[str, object] | None:
        """The reminder as the API shows it (schemas/user.py `Reminder`), or None."""
        if self.reminder_at is None or self.reminder_days is None:
            return None
        return {"at": self.reminder_at, "days": list(self.reminder_days)}

    @property
    def is_leaving(self) -> bool:
        """Waiting to be deleted: signed out everywhere, every access token refused."""
        return self.delete_after is not None

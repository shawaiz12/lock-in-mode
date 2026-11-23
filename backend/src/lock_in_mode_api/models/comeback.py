"""Coming back after a break (ADR 0021): workouts are eased for a week or three, then the
saved progress applies again. The progress itself is never lowered.

comebacks         per user and break: how long they were away, how long the ease-in lasts
                  (at most one open per user); linked from workout_sessions.comeback_id
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, func, text
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import ComebackEndReason


class Comeback(Base):
    """One return after 14+ days away.

    Saved when the first workout after the break is started, not when the break is
    noticed: until then the API works it out on each read. "I kept training elsewhere"
    on a comeback that isn't saved yet saves it already ended, so the same break isn't
    found again. A break is new when a set was ticked after `trained_until` of every
    comeback saved so far.
    """

    __tablename__ = "comebacks"
    __table_args__ = (
        CheckConstraint("away_days >= 14", name="away_days_min"),
        CheckConstraint("weeks IN (1, 3)", name="weeks_allowed"),
        CheckConstraint("workouts_per_week BETWEEN 2 AND 6", name="workouts_per_week_range"),
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ended_with_reason"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="end_order"),
        # One open comeback per user, guaranteed by the database.
        Index(
            "uq_comebacks_one_open_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The break it covers: the last ticked set before it (as the database stamped it, so
    # "a set ticked since?" compares one clock with itself), and the whole days until the
    # return.
    trained_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    away_days: Mapped[int] = mapped_column(SmallInteger)
    weeks: Mapped[int] = mapped_column(SmallInteger)  # 1: an easy week, 3: a ramp
    # Their answer when it started: one comeback week = this many trained workouts.
    workouts_per_week: Mapped[int] = mapped_column(SmallInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[ComebackEndReason | None] = mapped_column(enum_column(ComebackEndReason))

    @property
    def workouts(self) -> int:
        """How many trained workouts it eases."""
        return self.weeks * self.workouts_per_week

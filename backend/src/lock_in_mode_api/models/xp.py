"""The XP ledger (ADR 0035).

xp_events   one row per award: a trained workout, its new bests, a comeback, a Locked-in
            bonus (all tied to the workout's session), or a kept week (tied to the week).
            XP is only ever added: the total and the Lock In level never go down.

Each award can happen once (the unique indexes below), so an offline workout synced twice,
a retried finish or the backfill run again can never award twice: the insert simply finds
the row already there. Erased with the account (CASCADE) and in "Download my data".
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, func, text
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import XpSource


class XpEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        # A week award has its week and no workout; every other award has its workout.
        CheckConstraint(
            "(source = 'week') = (week_start IS NOT NULL AND session_id IS NULL)",
            name="week_or_workout",
        ),
        CheckConstraint(
            "source = 'week' OR session_id IS NOT NULL", name="workout_awards_have_a_session"
        ),
        Index(
            "uq_xp_events_session_source",
            "session_id",
            "source",
            unique=True,
            postgresql_where=text("session_id IS NOT NULL"),
        ),
        Index(
            "uq_xp_events_user_week",
            "user_id",
            "week_start",
            unique=True,
            postgresql_where=text("week_start IS NOT NULL"),
        ),
        # The total: one user's rows.
        Index("ix_xp_events_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[XpSource] = mapped_column(enum_column(XpSource))
    amount: Mapped[int] = mapped_column(SmallInteger)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE")
    )
    week_start: Mapped[date | None] = mapped_column(Date)  # Monday, on the user's calendar
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

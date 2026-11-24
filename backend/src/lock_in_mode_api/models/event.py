"""Funnel events (ADR 0025).

events   one row per thing that happened (signed up, workout finished, block complete…),
         recorded by the server in the same transaction as the action. Erased with the
         account (CASCADE) and when the user switches "Share usage data" off.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import EventName


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # The report: "who did X, and when".
        Index("ix_events_name_at", "name", "at"),
        # One user's timeline.
        Index("ix_events_user_id_at", "user_id", "at"),
        # A block is complete once: two requests racing can't record it twice.
        Index(
            "uq_events_block_complete_once",
            "user_id",
            text("(props ->> 'block')"),
            unique=True,
            postgresql_where=text("name = 'block_complete'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[EventName] = mapped_column(enum_column(EventName))
    # The database clock at the moment the row is written. clock_timestamp(), not now():
    # now() is the transaction's start, the same for every event of one request.
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    # Fixed, typed details per event (services/events.py): never free text or health data.
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

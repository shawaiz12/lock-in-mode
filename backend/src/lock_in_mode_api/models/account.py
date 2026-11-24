"""Deleting an account (ADR 0024).

account_deletion_reasons   one row per deleted account that gave a reason; nothing in it
                           points back to the person (no user id, no time of day)
"""

import uuid
from datetime import date

from sqlalchemy import Date, func
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import LeavingReason


class AccountDeletionReason(Base):
    """Why someone left. Written only when the account is actually erased, so a
    deletion cancelled by signing in again is never counted."""

    __tablename__ = "account_deletion_reasons"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    reason: Mapped[LeavingReason] = mapped_column(enum_column(LeavingReason))
    was_guest: Mapped[bool]
    # The day they asked (UTC), not when the cleanup got to it.
    left_on: Mapped[date] = mapped_column(Date)

"""Exercises a user swapped out because they hurt (ADR 0020).

swapped_out_exercises  per user and exercise: never picked again until brought back
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import BodyArea
from lock_in_mode_api.models.exercise import Exercise


class SwappedOutExercise(Base):
    """ "This hurts, swap it": the plan never picks this exercise for this user again.

    Deleting the row ("bring it back") lets it return in the next rebuild or block.
    """

    __tablename__ = "swapped_out_exercises"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    # The optional "Where does it hurt?" tap after the swap.
    body_area: Mapped[BodyArea | None] = mapped_column(enum_column(BodyArea))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    exercise: Mapped[Exercise] = relationship(lazy="raise")

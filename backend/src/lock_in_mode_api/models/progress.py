"""Progress per exercise (ADR 0019): the plan keeps the block's starting numbers, this keeps
how far each user has moved on from them.

exercise_targets  per user and exercise: suggested weight, sets +/-, hold, reps nudge
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base
from lock_in_mode_api.training.progression import Target


class ExerciseTarget(Base):
    """One user's progress on one exercise, in every workout and block it comes back in.

    A row exists once the exercise has been trained (or stepped by a feedback streak). No
    row = the plan's numbers as they are.
    """

    __tablename__ = "exercise_targets"
    __table_args__ = (
        CheckConstraint("weight_kg IS NULL OR weight_kg > 0", name="weight_positive"),
        CheckConstraint("set_change BETWEEN -1 AND 1", name="set_change_range"),
        CheckConstraint("seconds IS NULL OR seconds BETWEEN 1 AND 600", name="seconds_range"),
        CheckConstraint("reps_bonus BETWEEN 0 AND 5", name="reps_bonus_range"),
        CheckConstraint("short_runs >= 0", name="short_runs_not_negative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    weight_kg: Mapped[float | None] = mapped_column(Numeric(6, 2, asdecimal=False))
    set_change: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    seconds: Mapped[int | None] = mapped_column(SmallInteger)
    reps_bonus: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    short_runs: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def as_target(self) -> Target:
        return Target(
            weight_kg=self.weight_kg,
            set_change=self.set_change,
            seconds=self.seconds,
            reps_bonus=self.reps_bonus,
            short_runs=self.short_runs,
        )

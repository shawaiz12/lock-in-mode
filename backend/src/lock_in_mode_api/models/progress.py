"""Progress per exercise (ADR 0019): the plan keeps the block's starting numbers, this keeps
how far each user has moved on from them.

exercise_targets  per user and exercise: suggested weight, sets +/-, hold, reps nudge
interval_steps    per user: the step HIIT and finishers are served at (ADR 0023)
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import FitnessLevel
from lock_in_mode_api.training.intervals import State
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


class IntervalStep(Base):
    """One user's interval progress (ADR 0023): the step their HIIT and finishers are
    served at, the level it belongs to, and the good or short workouts in a row so far.

    One row per user, created the first time a workout with intervals counts. No row =
    the level's start. A row for another level is read as the new level's start.
    """

    __tablename__ = "interval_steps"
    __table_args__ = (
        CheckConstraint("step BETWEEN 0 AND 4", name="step_range"),
        CheckConstraint("good_runs BETWEEN 0 AND 1", name="good_runs_range"),
        CheckConstraint("short_runs BETWEEN 0 AND 1", name="short_runs_range"),
        CheckConstraint("good_runs = 0 OR short_runs = 0", name="one_run_at_a_time"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[FitnessLevel] = mapped_column(enum_column(FitnessLevel))
    step: Mapped[int] = mapped_column(SmallInteger)
    good_runs: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    short_runs: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def as_state(self) -> tuple[FitnessLevel, State]:
        return self.level, State(self.step, self.good_runs, self.short_runs)

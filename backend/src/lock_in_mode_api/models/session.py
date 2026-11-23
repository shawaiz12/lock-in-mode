"""Doing a workout: sessions, logged sets, and where the strength test placed the user
(ADR 0018).

workout_sessions  one per planned workout; at most one open (unfinished) per user;
                  linked to a comeback when it was eased after a break (ADR 0021)
 └ set_logs       one row per set the user ticks: reps and/or seconds, optional weight
movement_rungs    per user and movement: the difficulty the strength test placed them on
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import Feedback, MovementSlot
from lock_in_mode_api.models.plan import PlannedWorkout


class WorkoutSession(Base):
    """One go at a planned workout. Open until finished; finishing early still counts."""

    __tablename__ = "workout_sessions"
    __table_args__ = (
        # A workout is done once: "Continue" reopens the same session.
        UniqueConstraint("planned_workout_id", name="uq_workout_sessions_planned_workout_id"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="finish_order"),
        CheckConstraint("feedback IS NULL OR finished_at IS NOT NULL", name="feedback_at_finish"),
        CheckConstraint(
            "(comeback_id IS NULL) = (comeback_week IS NULL)", name="comeback_with_week"
        ),
        CheckConstraint(
            "comeback_week IS NULL OR comeback_week BETWEEN 1 AND 3", name="comeback_week_range"
        ),
        # One open session per user, guaranteed by the database (like one current plan).
        Index(
            "uq_workout_sessions_one_open_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("finished_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # Stored here as well as through the plan: "this user's open session" and "this
    # user's last results" are the common questions, and the index above needs it.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    planned_workout_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planned_workouts.id", ondelete="CASCADE")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL when the user skipped the question: no answer is not "just right".
    feedback: Mapped[Feedback | None] = mapped_column(enum_column(Feedback))
    # Eased after a break (ADR 0021): which comeback, and which of its weeks. Saved when
    # the workout starts, so it keeps the numbers it started with whatever happens next.
    # Such a session changes no progress. No ON DELETE: comebacks go only with the user,
    # who takes their sessions along.
    comeback_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comebacks.id"), index=True)
    comeback_week: Mapped[int | None] = mapped_column(SmallInteger)

    planned_workout: Mapped[PlannedWorkout] = relationship(lazy="raise")
    sets: Mapped[list["SetLog"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="(SetLog.logged_at, SetLog.set_number)",
        lazy="raise",
        passive_deletes=True,
    )


class SetLog(Base):
    """One ticked set. Ticking the same set again replaces it (fixing a typo)."""

    __tablename__ = "set_logs"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "planned_exercise_id",
            "set_number",
            name="uq_set_logs_session_exercise_set",
        ),
        CheckConstraint("set_number BETWEEN 1 AND 20", name="set_number_range"),
        CheckConstraint("reps IS NOT NULL OR seconds IS NOT NULL", name="reps_or_seconds"),
        CheckConstraint("reps IS NULL OR reps BETWEEN 0 AND 1000", name="reps_range"),
        CheckConstraint("seconds IS NULL OR seconds BETWEEN 0 AND 10800", name="seconds_range"),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg BETWEEN 0 AND 1000", name="weight_kg_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE")
    )
    # Indexed: "what did I lift last time on this exercise?" joins through it.
    planned_exercise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planned_exercises.id", ondelete="CASCADE"), index=True
    )
    set_number: Mapped[int] = mapped_column(SmallInteger)
    reps: Mapped[int | None] = mapped_column(SmallInteger)
    # Numeric, not float: 22.5 kg must stay exactly 22.5. asdecimal=False hands Python a
    # float, so the API sends a JSON number, not a string.
    weight_kg: Mapped[float | None] = mapped_column(Numeric(6, 2, asdecimal=False))
    seconds: Mapped[int | None] = mapped_column(SmallInteger)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[WorkoutSession] = relationship(back_populates="sets", lazy="raise")


class MovementRung(Base):
    """Where the strength test placed the user for one movement (KB section 2).

    `difficulty` (1-5) is what the picker aims for in that movement's bodyweight moves,
    in this block's remaining workouts and every block after (ADR 0018).
    """

    __tablename__ = "movement_rungs"
    __table_args__ = (CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    movement: Mapped[MovementSlot] = mapped_column(enum_column(MovementSlot), primary_key=True)
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    # The test result behind it (reps, or seconds for the plank), shown back to the user.
    result: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

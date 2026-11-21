"""Saved training blocks and their workout queue (ADR 0014 decision 3, ADR 0017).

plans               one row per training block; at most one current plan per user
 └ planned_workouts  the queue, in order: position 1, 2, 3, ... across the whole block
    └ planned_exercises  warm-up, main, finisher and cool-down, with the numbers to hit

The generator's output is stored as it was made, so a change to the exercise library
never silently changes a plan in progress.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import (
    PlanEndReason,
    RoutineKind,
    SessionKind,
    WorkoutFormat,
    WorkoutPart,
    WorkoutStatus,
)
from lock_in_mode_api.models.exercise import Exercise


class Plan(Base):
    """One training block: the routine, the reasons behind it, and every workout."""

    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("user_id", "block_number", name="uq_plans_user_block_number"),
        CheckConstraint("block_number >= 1", name="block_number_positive"),
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ended_with_reason"),
        # The database itself guarantees one current plan per user, even if two requests
        # race (a double tap on "start next block"). A partial index: only rows that
        # match the WHERE are in it, so ended plans don't count.
        Index(
            "uq_plans_one_current_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # 1, 2, 3, ... for this user. Freshens the small moves each block (ADR 0017).
    block_number: Mapped[int] = mapped_column(SmallInteger)
    routine_kind: Mapped[RoutineKind] = mapped_column(enum_column(RoutineKind))
    # Plain-language "why" lines for the plan reveal screen (ADR 0014 decision 6).
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # Suggested day for each session of a week, in queue order: 0 = Monday ... 6 = Sunday.
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    uses_push_pull_legs: Mapped[bool]
    weeks: Mapped[int] = mapped_column(SmallInteger)  # build-up weeks + the recovery week
    # The answers this plan was built from (training.plan_types.PlanAnswers).
    generated_from: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # NULL = the current plan.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[PlanEndReason | None] = mapped_column(enum_column(PlanEndReason))

    # lazy="raise": async code can't load relationships behind your back, so every query
    # must say what it needs (selectinload). A forgotten one fails loudly in tests.
    # passive_deletes: deleting a plan leaves its rows to ON DELETE CASCADE in the
    # database instead of loading every workout and exercise first.
    workouts: Mapped[list["PlannedWorkout"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlannedWorkout.position",
        lazy="raise",
        passive_deletes=True,
    )


class PlannedWorkout(Base):
    """One workout in the queue. The next workout is the first pending one."""

    __tablename__ = "planned_workouts"
    __table_args__ = (
        UniqueConstraint("plan_id", "position", name="uq_planned_workouts_plan_position"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("week >= 1", name="week_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)  # queue order across the block
    week: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[SessionKind] = mapped_column(enum_column(SessionKind))
    letter: Mapped[str] = mapped_column(String(1), default="", server_default="")
    title: Mapped[str] = mapped_column(String(40))
    format: Mapped[WorkoutFormat] = mapped_column(enum_column(WorkoutFormat))
    recovery: Mapped[bool] = mapped_column(default=False, server_default=false())
    main_minutes: Mapped[int] = mapped_column(SmallInteger)
    total_minutes: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[WorkoutStatus] = mapped_column(
        enum_column(WorkoutStatus),
        default=WorkoutStatus.PENDING,
        server_default=WorkoutStatus.PENDING.value,
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[Plan] = relationship(back_populates="workouts", lazy="raise")
    exercises: Mapped[list["PlannedWorkoutExercise"]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="PlannedWorkoutExercise.position",
        lazy="raise",
        passive_deletes=True,
    )


class PlannedWorkoutExercise(Base):
    """One exercise in a planned workout, with the numbers to hit (table planned_exercises)."""

    __tablename__ = "planned_exercises"
    __table_args__ = (
        UniqueConstraint(
            "planned_workout_id",
            "part",
            "position",
            name="uq_planned_exercises_workout_part_position",
        ),
        CheckConstraint("sets >= 1", name="sets_positive"),
        CheckConstraint("reps_min IS NULL OR reps_min <= reps_max", name="reps_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    planned_workout_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planned_workouts.id", ondelete="CASCADE")
    )
    part: Mapped[WorkoutPart] = mapped_column(enum_column(WorkoutPart))
    position: Mapped[int] = mapped_column(SmallInteger)  # order within its part
    # RESTRICT: an exercise used by a saved plan can't be deleted from the library.
    # Indexed because Postgres doesn't index foreign keys itself, and that check (and
    # "which plans use this exercise?") would otherwise scan the whole table.
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    sets: Mapped[int] = mapped_column(SmallInteger)  # rounds, for circuits and intervals
    reps_min: Mapped[int | None] = mapped_column(SmallInteger)  # NULL: timed or open test
    reps_max: Mapped[int | None] = mapped_column(SmallInteger)
    seconds: Mapped[int | None] = mapped_column(SmallInteger)
    rest_seconds: Mapped[int] = mapped_column(SmallInteger)
    reps_in_reserve: Mapped[int | None] = mapped_column(SmallInteger)  # strength only
    effort: Mapped[int | None] = mapped_column(SmallInteger)  # cardio: 1-10 talk test
    # Exercises with the same group number are done back to back (supersets, circuits).
    group_number: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    practice_sets: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    is_test: Mapped[bool] = mapped_column(default=False, server_default=false())

    workout: Mapped[PlannedWorkout] = relationship(back_populates="exercises", lazy="raise")
    exercise: Mapped[Exercise] = relationship(lazy="raise")

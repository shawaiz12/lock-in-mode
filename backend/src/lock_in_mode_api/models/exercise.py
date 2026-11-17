import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Table,
    Text,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import (
    ExerciseCategory,
    ExerciseType,
    Impact,
    MovementSlot,
    MuscleGroup,
)

exercise_alternatives = Table(
    "exercise_alternatives",
    Base.metadata,
    Column("exercise_id", ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True),
    Column("alternative_id", ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True),
    CheckConstraint("exercise_id <> alternative_id", name="not_self"),
)


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        CheckConstraint("effectiveness BETWEEN 1 AND 5", name="effectiveness_range"),
        CheckConstraint("harder_variant_id <> id", name="harder_variant_not_self"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[ExerciseCategory] = mapped_column(enum_column(ExerciseCategory))
    movement_slot: Mapped[MovementSlot] = mapped_column(enum_column(MovementSlot))
    exercise_type: Mapped[ExerciseType] = mapped_column(enum_column(ExerciseType))

    # Weekly set counting (ADR 0010): a set counts 1 for the primary, 0.5 per secondary.
    # NULL for cardio and mobility, which don't count towards muscle sets.
    primary_muscle: Mapped[MuscleGroup | None] = mapped_column(enum_column(MuscleGroup))
    secondary_muscles: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), default=list, server_default="{}"
    )
    targets: Mapped[list[str]] = mapped_column(  # MuscleHead values
        ARRAY(String(30)), default=list, server_default="{}"
    )

    equipment: Mapped[list[str]] = mapped_column(  # Equipment values; empty = none
        ARRAY(String(30)), default=list, server_default="{}"
    )
    also_needs: Mapped[str | None] = mapped_column(String(100))
    home_only: Mapped[bool] = mapped_column(default=False, server_default=false())

    difficulty: Mapped[int] = mapped_column(SmallInteger)
    effectiveness: Mapped[int | None] = mapped_column(SmallInteger)
    impact: Mapped[Impact] = mapped_column(
        enum_column(Impact), default=Impact.NONE, server_default=Impact.NONE.value
    )
    not_suitable_for: Mapped[list[str]] = mapped_column(  # BodyLimit values
        ARRAY(String(30)), default=list, server_default="{}"
    )
    is_timed: Mapped[bool] = mapped_column(default=False, server_default=false())
    steps: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    cues: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    common_mistake: Mapped[str | None] = mapped_column(Text)
    demo_url: Mapped[str | None] = mapped_column(String(500))
    harder_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

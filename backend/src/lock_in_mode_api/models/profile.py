import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, false, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base, enum_column
from lock_in_mode_api.models.enums import FitnessLevel, Goal, Location


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("days_per_week BETWEEN 2 AND 6", name="days_per_week_range"),
        CheckConstraint(
            "minutes_per_session IN (10, 20, 30, 45)", name="minutes_per_session_allowed"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    goal: Mapped[Goal] = mapped_column(enum_column(Goal))
    level: Mapped[FitnessLevel] = mapped_column(enum_column(FitnessLevel))
    location: Mapped[Location] = mapped_column(enum_column(Location))
    equipment: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), default=list, server_default="{}"
    )
    limits: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list, server_default="{}")
    days_per_week: Mapped[int]
    minutes_per_session: Mapped[int]
    women_home_track: Mapped[bool] = mapped_column(default=False, server_default=false())
    needs_low_intensity: Mapped[bool] = mapped_column(default=False, server_default=false())
    safety_screened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

"""Onboarding answers in and out (ADR 0012)."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
)

from lock_in_mode_api.models.enums import (
    BodyLimit,
    Equipment,
    FitnessLevel,
    Goal,
    Location,
    Obstacle,
    ShoulderDay,
)
from lock_in_mode_api.training.routine_rules import bro_split_available

# Must match models.profile.SESSION_MINUTES (a test checks). null = no limit.
type SessionMinutes = Literal[10, 20, 30, 45, 60, 75, 90]


def _unique_in_enum_order[E: Enum](values: list[E], enum_cls: type[E]) -> list[E]:
    """Drop duplicates and store in a fixed order, so the same answers look the same."""
    chosen = set(values)
    return [member for member in enum_cls if member in chosen]


class ProfileWrite(BaseModel):
    """Every onboarding answer. PUT replaces the whole profile, so send all of them."""

    # Unknown fields are an error, so nobody can set needs_low_intensity here.
    model_config = ConfigDict(extra="forbid")

    goal: Goal
    level: FitnessLevel = Field(description="From training history, not self-rating.")
    location: Location
    equipment: list[Equipment] = Field(
        default_factory=list,
        description="Home only: dumbbells, resistance_bands, pull_up_bar. Empty for gym.",
    )
    limits: list[BodyLimit] = Field(default_factory=list)
    days_per_week: int = Field(ge=2, le=6)
    minutes_per_session: SessionMinutes | None = Field(description="null = no limit.")
    women_home_track: bool = False
    prefers_bro_split: bool = Field(
        default=False, description="Used only when bro_split_available is true."
    )
    shoulder_day: ShoulderDay = Field(
        default=ShoulderDay.PUSH, description="Used only for push pull legs."
    )
    obstacles: list[Obstacle] = Field(
        default_factory=list, description="Changes tips, reminders and quests, never the plan."
    )

    # Field validators run in field order, so `location` is already in info.data here.
    @field_validator("equipment")
    @classmethod
    def _home_equipment_only(cls, value: list[Equipment], info: ValidationInfo) -> list[Equipment]:
        if Equipment.GYM in value:
            raise ValueError("'gym' isn't home equipment; set location to 'gym' instead")
        if value and info.data.get("location") == Location.GYM:
            raise ValueError("Gym users have all the equipment; send an empty list")
        return _unique_in_enum_order(value, Equipment)

    @field_validator("women_home_track")
    @classmethod
    def _home_track_is_home_only(cls, value: bool, info: ValidationInfo) -> bool:
        if value and info.data.get("location") == Location.GYM:
            raise ValueError("The women-at-home track is for home workouts only")
        return value

    @field_validator("limits")
    @classmethod
    def _unique_limits(cls, value: list[BodyLimit]) -> list[BodyLimit]:
        return _unique_in_enum_order(value, BodyLimit)

    @field_validator("obstacles")
    @classmethod
    def _unique_obstacles(cls, value: list[Obstacle]) -> list[Obstacle]:
        return _unique_in_enum_order(value, Obstacle)


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    goal: Goal
    level: FitnessLevel
    location: Location
    equipment: list[Equipment]
    limits: list[BodyLimit]
    days_per_week: int
    minutes_per_session: int | None
    women_home_track: bool
    prefers_bro_split: bool
    shoulder_day: ShoulderDay
    obstacles: list[Obstacle]
    needs_low_intensity: bool
    safety_screened_at: datetime | None = Field(
        description="null until the safety screen is done; required before workout 1."
    )
    pact_signed_at: datetime | None = Field(
        description="null until the Lock In pact is signed (`POST /me/pact`), the last "
        "onboarding step. Changing answers later keeps it."
    )
    pact_due: bool = Field(
        default=False,
        description="Show the pact now: the safety screen is done, the pact isn't signed and "
        "no plan was ever made. People who already train never get it in the way.",
    )
    created_at: datetime
    updated_at: datetime

    @computed_field(description="Show the 'push pull legs or bro split?' choice.")  # type: ignore[prop-decorator]
    @property
    def bro_split_available(self) -> bool:
        return bro_split_available(self)


class SafetyScreen(BaseModel):
    """Four yes/no answers. Only the result is stored, never the answers (ADR 0012)."""

    model_config = ConfigDict(extra="forbid")

    heart_condition: bool
    chest_pain_when_active: bool
    pregnant: bool
    recent_surgery_or_injury: bool

    @property
    def any_yes(self) -> bool:
        return (
            self.heart_condition
            or self.chest_pain_when_active
            or self.pregnant
            or self.recent_surgery_or_injury
        )

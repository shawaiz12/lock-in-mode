"""Which exercises a user can do, and which need a warning (ADR 0010, ADR 0013).

Pure functions: the API filters with them and the plan generator will pick with them.
"""

from collections.abc import Sequence
from typing import Protocol

from lock_in_mode_api.models.enums import BodyLimit, Caution, Equipment, Impact, Location

# Gym users have everything a gym has, but never bands: nobody trains with bands in a
# gym, so band exercises go only to home users who own bands (ADR 0010).
GYM_KIT = frozenset({Equipment.DUMBBELLS, Equipment.PULL_UP_BAR, Equipment.GYM})

# Jumping and pounding: out for low-intensity plans and the quiet track (KB section 2).
HIGH_IMPACT = frozenset({Impact.MEDIUM, Impact.HIGH})


class UserSetup(Protocol):
    """The profile answers these rules read. Profile rows fit."""

    @property
    def location(self) -> Location: ...
    @property
    def equipment(self) -> Sequence[str]: ...
    @property
    def limits(self) -> Sequence[str]: ...
    @property
    def needs_low_intensity(self) -> bool: ...
    @property
    def women_home_track(self) -> bool: ...


class ExerciseFacts(Protocol):
    """The exercise fields these rules read. Exercise rows fit."""

    @property
    def equipment(self) -> Sequence[str]: ...
    @property
    def home_only(self) -> bool: ...
    @property
    def impact(self) -> Impact: ...
    @property
    def not_suitable_for(self) -> Sequence[str]: ...


def user_kit(location: Location, equipment: Sequence[str]) -> frozenset[Equipment]:
    """Everything this user can train with."""
    if location == Location.GYM:
        return GYM_KIT
    return frozenset(Equipment(item) for item in equipment)


def can_do(exercise: ExerciseFacts, user: UserSetup) -> bool:
    """They own every piece of kit it needs, and it isn't a home trick shown to a gym user."""
    kit = user_kit(user.location, user.equipment)
    if user.location == Location.GYM and exercise.home_only:
        return False
    return all(Equipment(item) in kit for item in exercise.equipment)


def cautions(exercise: ExerciseFacts, user: UserSetup) -> list[Caution]:
    """Reasons to warn this user about this exercise, in a fixed order."""
    found = [
        Caution(limit)
        for limit in BodyLimit
        if limit in user.limits and limit in exercise.not_suitable_for
    ]
    if exercise.impact in HIGH_IMPACT:
        if user.needs_low_intensity:
            found.append(Caution.LOW_INTENSITY)
        if user.women_home_track:
            found.append(Caution.NOT_QUIET)
    return found

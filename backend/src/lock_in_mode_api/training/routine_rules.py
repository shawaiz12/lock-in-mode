"""Which routines a user may get (Knowledge Base section 4).

These rules decide what the app may *offer*, so they live here once and both the API
(e.g. `bro_split_available` on the profile) and the plan generator use them.
"""

from collections.abc import Sequence
from typing import Protocol

from lock_in_mode_api.models.enums import Equipment, FitnessLevel, Goal, Location

BRO_SPLIT_DAYS = 5
BRO_SPLIT_MIN_MINUTES = 45


class RoutineInputs(Protocol):
    """The onboarding answers the routine rules read. Profile rows and schemas both fit."""

    @property
    def goal(self) -> Goal: ...
    @property
    def level(self) -> FitnessLevel: ...
    @property
    def location(self) -> Location: ...
    @property
    def equipment(self) -> Sequence[str]: ...
    @property
    def days_per_week(self) -> int: ...
    @property
    def minutes_per_session(self) -> int | None: ...


def bro_split_available(answers: RoutineInputs) -> bool:
    """Bro split is an opt-in, offered only when it can be done well (ADR 0012).

    Needs: build muscle; some experience or more; exactly 5 days; a gym or dumbbells
    (enough exercises for a whole day per body part); 45+ minutes or no limit.
    """
    has_the_kit = answers.location == Location.GYM or Equipment.DUMBBELLS in answers.equipment
    has_the_time = (
        answers.minutes_per_session is None or answers.minutes_per_session >= BRO_SPLIT_MIN_MINUTES
    )
    return (
        answers.goal == Goal.BUILD_MUSCLE
        and answers.level != FitnessLevel.BEGINNER
        and answers.days_per_week == BRO_SPLIT_DAYS
        and has_the_kit
        and has_the_time
    )

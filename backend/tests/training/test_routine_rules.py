"""Bro split eligibility (Knowledge Base section 4, ADR 0012). No database needed."""

from dataclasses import dataclass, field, replace

import pytest

from lock_in_mode_api.models.enums import Equipment, FitnessLevel, Goal, Location
from lock_in_mode_api.training.routine_rules import bro_split_available


@dataclass(frozen=True)
class Answers:
    """A user who qualifies; each test breaks one condition."""

    goal: Goal = Goal.BUILD_MUSCLE
    level: FitnessLevel = FitnessLevel.SOME_EXPERIENCE
    location: Location = Location.GYM
    equipment: list[str] = field(default_factory=list)
    days_per_week: int = 5
    minutes_per_session: int | None = 45


QUALIFIES = Answers()


def test_a_qualifying_gym_user_gets_the_choice() -> None:
    assert bro_split_available(QUALIFIES)


@pytest.mark.parametrize(
    "answers",
    [
        replace(QUALIFIES, level=FitnessLevel.EXPERIENCED),
        replace(QUALIFIES, minutes_per_session=None),  # no limit
        replace(QUALIFIES, minutes_per_session=90),
        replace(QUALIFIES, location=Location.HOME, equipment=[Equipment.DUMBBELLS]),
        replace(
            QUALIFIES,
            location=Location.HOME,
            equipment=[Equipment.DUMBBELLS, Equipment.PULL_UP_BAR],
        ),
    ],
)
def test_also_qualifies(answers: Answers) -> None:
    assert bro_split_available(answers)


@pytest.mark.parametrize(
    "answers",
    [
        replace(QUALIFIES, goal=Goal.STRENGTH),
        replace(QUALIFIES, goal=Goal.LOSE_FAT),
        replace(QUALIFIES, level=FitnessLevel.BEGINNER),
        replace(QUALIFIES, days_per_week=4),
        replace(QUALIFIES, days_per_week=6),
        replace(QUALIFIES, minutes_per_session=30),
        replace(QUALIFIES, location=Location.HOME),  # no equipment
        replace(
            QUALIFIES,
            location=Location.HOME,
            equipment=[Equipment.RESISTANCE_BANDS, Equipment.PULL_UP_BAR],
        ),
    ],
)
def test_does_not_qualify(answers: Answers) -> None:
    assert not bro_split_available(answers)

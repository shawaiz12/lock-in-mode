"""Promises the shipped exercise library makes to the plan generator (ADR 0011).

These test the real file, not made-up exercises: if an edit removes the last exercise
that hits a head for some kind of user, CI fails before that user gets a broken plan.
"""

import pytest

from lock_in_mode_api.models.enums import Equipment, MovementSlot, MuscleHead
from lock_in_mode_api.seed.schema import SeedExercise, SeedLibrary, load_library

GYM_KIT = {Equipment.DUMBBELLS, Equipment.PULL_UP_BAR, Equipment.GYM}  # never bands (ADR 0010)


@pytest.fixture(scope="module")
def library() -> SeedLibrary:
    return load_library()


def _available(library: SeedLibrary, kit: set[Equipment], *, at_home: bool) -> list[SeedExercise]:
    """Same availability rule the plan generator will use (ADR 0010)."""
    return [
        exercise
        for exercise in library.exercises
        if set(exercise.equipment) <= kit and (at_home or not exercise.home_only)
    ]


def _heads(exercises: list[SeedExercise]) -> set[MuscleHead]:
    return {head for exercise in exercises for head in exercise.targets}


def test_the_whole_exercise_database_is_seeded(library: SeedLibrary) -> None:
    assert len(library.exercises) >= 255


def test_gym_users_can_hit_every_head_and_fill_every_slot(library: SeedLibrary) -> None:
    gym = _available(library, GYM_KIT, at_home=False)

    assert _heads(gym) == set(MuscleHead)
    assert {exercise.movement_slot for exercise in gym} == set(MovementSlot)


def test_gym_users_never_get_bands_or_home_tricks(library: SeedLibrary) -> None:
    gym = _available(library, GYM_KIT, at_home=False)

    assert not [e.slug for e in gym if Equipment.RESISTANCE_BANDS in e.equipment or e.home_only]


@pytest.mark.parametrize(
    "kit",
    [
        {Equipment.RESISTANCE_BANDS},
        {Equipment.DUMBBELLS},
        {Equipment.DUMBBELLS, Equipment.RESISTANCE_BANDS, Equipment.PULL_UP_BAR},
    ],
)
def test_home_users_with_bands_or_dumbbells_can_hit_every_head(
    library: SeedLibrary, kit: set[Equipment]
) -> None:
    assert _heads(_available(library, kit, at_home=True)) == set(MuscleHead)


def test_home_users_with_no_equipment_can_hit_every_head(library: SeedLibrary) -> None:
    # Backpack hammer and reverse curls close the arm and forearm gaps the knowledge base
    # mentions (ADR 0011). Without kit there is still no vertical pull: rows fill that slot.
    assert _heads(_available(library, set(), at_home=True)) == set(MuscleHead)


def test_every_category_has_a_beginner_exercise(library: SeedLibrary) -> None:
    # Beginners need somewhere to start: each category has at least one difficulty-1 move.
    categories = {exercise.category for exercise in library.exercises}
    beginner = {exercise.category for exercise in library.exercises if exercise.difficulty == 1}

    assert beginner == categories

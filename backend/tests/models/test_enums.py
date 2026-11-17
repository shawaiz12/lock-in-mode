"""Vocabularies the seed file and the plan generator rely on (ADR 0010)."""

from lock_in_mode_api.models.enums import HEAD_GROUP, MuscleGroup, MuscleHead


def test_every_head_belongs_to_a_muscle_group() -> None:
    # A new head without a group would crash the head-coverage check at runtime.
    assert set(HEAD_GROUP) == set(MuscleHead)


def test_every_trained_muscle_group_has_a_head() -> None:
    assert set(HEAD_GROUP.values()) == set(MuscleGroup)

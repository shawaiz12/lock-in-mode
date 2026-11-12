"""Database-level rules for the exercise library (see ADR 0003).

These tests talk to real Postgres through `db_session`, and every change is
rolled back when each test ends.
"""

import uuid

import pytest
from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, exercise_alternatives
from lock_in_mode_api.models.enums import ExerciseCategory


def _valid_exercise(slug: str, **overrides: object) -> Exercise:
    """An exercise that passes every constraint; tests change one field at a time."""
    fields: dict[str, object] = {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "category": ExerciseCategory.PUSH,
        "difficulty": 2,
    }
    fields.update(overrides)
    return Exercise(**fields)


async def _create_exercises(session: AsyncSession, *slugs: str) -> list[Exercise]:
    """Insert one valid exercise per slug and return them (with ids)."""
    exercises = [_valid_exercise(slug) for slug in slugs]
    session.add_all(exercises)
    await session.flush()
    return exercises


async def _link_alternative(
    session: AsyncSession, exercise_id: uuid.UUID, alternative_id: uuid.UUID
) -> None:
    await session.execute(
        insert(exercise_alternatives).values(exercise_id=exercise_id, alternative_id=alternative_id)
    )


async def _count_alternative_rows_touching(session: AsyncSession, exercise_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(exercise_alternatives)
        .where(
            or_(
                exercise_alternatives.c.exercise_id == exercise_id,
                exercise_alternatives.c.alternative_id == exercise_id,
            )
        )
    )
    return count or 0


# --- exercises table --------------------------------------------------------


async def test_valid_exercise_is_saved(db_session: AsyncSession) -> None:
    db_session.add(_valid_exercise("push-up"))
    await db_session.flush()  # raises if any constraint fails


async def test_slug_must_be_unique(db_session: AsyncSession) -> None:
    await _create_exercises(db_session, "push-up")
    db_session.add(_valid_exercise("push-up", name="Another Push-up"))

    with pytest.raises(IntegrityError, match="uq_exercises_slug"):
        await db_session.flush()


@pytest.mark.parametrize("difficulty", [1, 5])
async def test_difficulty_accepts_boundaries(db_session: AsyncSession, difficulty: int) -> None:
    db_session.add(_valid_exercise("push-up", difficulty=difficulty))
    await db_session.flush()


@pytest.mark.parametrize("difficulty", [0, 6])
async def test_difficulty_rejects_out_of_range(db_session: AsyncSession, difficulty: int) -> None:
    db_session.add(_valid_exercise("push-up", difficulty=difficulty))

    with pytest.raises(IntegrityError, match="ck_exercises_difficulty_range"):
        await db_session.flush()


# --- harder variant ladder --------------------------------------------------


async def test_harder_variant_link_is_saved(db_session: AsyncSession) -> None:
    easy, hard = await _create_exercises(db_session, "knee-push-up", "push-up")

    easy.harder_variant_id = hard.id
    await db_session.flush()


async def test_exercise_cannot_be_its_own_harder_variant(db_session: AsyncSession) -> None:
    (push_up,) = await _create_exercises(db_session, "push-up")

    push_up.harder_variant_id = push_up.id

    with pytest.raises(IntegrityError, match="ck_exercises_harder_variant_not_self"):
        await db_session.flush()


async def test_two_exercises_cannot_share_a_harder_variant(db_session: AsyncSession) -> None:
    """Ladders can't merge (ADR 0003): each exercise has at most one easier version."""
    knee, incline, push_up = await _create_exercises(
        db_session, "knee-push-up", "incline-push-up", "push-up"
    )
    knee.harder_variant_id = push_up.id
    await db_session.flush()

    incline.harder_variant_id = push_up.id

    with pytest.raises(IntegrityError, match="uq_exercises_harder_variant_id"):
        await db_session.flush()


async def test_deleting_harder_variant_unlinks_it(db_session: AsyncSession) -> None:
    """ON DELETE SET NULL: the easier exercise survives, its link is cleared."""
    easy, hard = await _create_exercises(db_session, "knee-push-up", "push-up")
    easy.harder_variant_id = hard.id
    await db_session.flush()

    # Core DELETE, not session.delete(): we're testing what the DATABASE does.
    await db_session.execute(delete(Exercise).where(Exercise.id == hard.id))

    # Read the column straight from the DB; the ORM object in memory is stale.
    link = await db_session.scalar(select(Exercise.harder_variant_id).where(Exercise.id == easy.id))
    assert link is None


# --- equipment alternatives (join table) ------------------------------------


async def test_alternative_link_is_saved(db_session: AsyncSession) -> None:
    pull_up, band_row = await _create_exercises(db_session, "pull-up", "band-row")

    await _link_alternative(db_session, pull_up.id, band_row.id)

    assert await _count_alternative_rows_touching(db_session, pull_up.id) == 1


async def test_exercise_cannot_be_its_own_alternative(db_session: AsyncSession) -> None:
    (pull_up,) = await _create_exercises(db_session, "pull-up")

    with pytest.raises(IntegrityError, match="ck_exercise_alternatives_not_self"):
        await _link_alternative(db_session, pull_up.id, pull_up.id)


async def test_same_alternative_pair_cannot_be_added_twice(db_session: AsyncSession) -> None:
    pull_up, band_row = await _create_exercises(db_session, "pull-up", "band-row")
    await _link_alternative(db_session, pull_up.id, band_row.id)

    with pytest.raises(IntegrityError, match="pk_exercise_alternatives"):
        await _link_alternative(db_session, pull_up.id, band_row.id)


async def test_alternative_must_be_an_existing_exercise(db_session: AsyncSession) -> None:
    (pull_up,) = await _create_exercises(db_session, "pull-up")

    with pytest.raises(IntegrityError, match="fk_exercise_alternatives_alternative_id_exercises"):
        await _link_alternative(db_session, pull_up.id, uuid.uuid4())


@pytest.mark.parametrize("deleted_side", ["exercise", "alternative"])
async def test_deleting_either_exercise_removes_the_alternative_row(
    db_session: AsyncSession, deleted_side: str
) -> None:
    """ON DELETE CASCADE on both columns: a link is meaningless once either end is gone."""
    pull_up, band_row = await _create_exercises(db_session, "pull-up", "band-row")
    await _link_alternative(db_session, pull_up.id, band_row.id)
    deleted, survivor = (pull_up, band_row) if deleted_side == "exercise" else (band_row, pull_up)

    await db_session.execute(delete(Exercise).where(Exercise.id == deleted.id))

    assert await _count_alternative_rows_touching(db_session, survivor.id) == 0

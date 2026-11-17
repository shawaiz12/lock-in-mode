"""Loading the seed file into Postgres (ADR 0009). Each test is rolled back afterwards."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, exercise_alternatives
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import SeedLibrary, load_library


def _exercise(slug: str, **overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "slug": slug,
        "name": slug.replace("-", " ").capitalize(),
        "category": "push",
        "movement_slot": "horizontal_push",
        "exercise_type": "compound",
        "primary_muscle": "chest",
        "targets": ["chest_mid"],
        "difficulty": 2,
        "effectiveness": 3,
        "steps": ["Step one.", "Step two.", "Step three."],
        "cues": ["Cue one.", "Cue two."],
        "common_mistake": "A mistake.",
    }
    fields.update(overrides)
    return fields


def _library(*exercises: dict[str, object]) -> SeedLibrary:
    return SeedLibrary.model_validate({"exercises": list(exercises)})


async def _row(session: AsyncSession, slug: str) -> Exercise:
    row = await session.scalar(select(Exercise).where(Exercise.slug == slug))
    assert row is not None
    return row


async def _harder_slug(session: AsyncSession, slug: str) -> str | None:
    row = await _row(session, slug)
    if row.harder_variant_id is None:
        return None
    return await session.scalar(select(Exercise.slug).where(Exercise.id == row.harder_variant_id))


# --- the real file --------------------------------------------------------------


async def test_the_shipped_library_loads_completely(db_session: AsyncSession) -> None:
    library = load_library()

    report = await load_exercises(db_session, library)

    assert len(report.inserted) == len(library.exercises)
    count = await db_session.scalar(select(func.count()).select_from(Exercise))
    assert count == len(library.exercises)
    assert await _harder_slug(db_session, "push-up") == "close-grip-push-up"


async def test_loading_twice_changes_nothing(db_session: AsyncSession) -> None:
    # The whole point of an idempotent loader: run it on every deploy, safely.
    library = load_library()
    await load_exercises(db_session, library)

    report = await load_exercises(db_session, library)

    assert report.inserted == []
    assert report.updated == []
    assert report.links_changed == 0
    assert report.unchanged == len(library.exercises)


# --- updates -----------------------------------------------------------------------


async def test_a_changed_field_is_updated_in_place(db_session: AsyncSession) -> None:
    await load_exercises(db_session, _library(_exercise("push-up")))
    original_id = (await _row(db_session, "push-up")).id

    report = await load_exercises(
        db_session, _library(_exercise("push-up", common_mistake="Hips sagging."))
    )

    row = await _row(db_session, "push-up")
    assert report.updated == ["push-up"]
    assert row.common_mistake == "Hips sagging."
    assert row.id == original_id  # same row: anything pointing at it keeps working


async def test_ladder_links_are_set_after_every_row_exists(db_session: AsyncSession) -> None:
    # The harder variant comes later in the file than the exercise that points at it.
    await load_exercises(
        db_session,
        _library(
            _exercise("knee-push-up", difficulty=1, harder="push-up"),
            _exercise("push-up", difficulty=2),
        ),
    )

    assert await _harder_slug(db_session, "knee-push-up") == "push-up"


async def test_swapping_ladder_links_does_not_trip_the_unique_rule(
    db_session: AsyncSession,
) -> None:
    # a -> c and b -> d become a -> d and b -> c: each target is briefly "taken".
    await load_exercises(
        db_session,
        _library(
            _exercise("a", harder="c"),
            _exercise("b", harder="d"),
            _exercise("c", difficulty=3),
            _exercise("d", difficulty=3),
        ),
    )

    report = await load_exercises(
        db_session,
        _library(
            _exercise("a", harder="d"),
            _exercise("b", harder="c"),
            _exercise("c", difficulty=3),
            _exercise("d", difficulty=3),
        ),
    )

    assert report.links_changed == 2
    assert await _harder_slug(db_session, "a") == "d"
    assert await _harder_slug(db_session, "b") == "c"


# --- nothing is deleted --------------------------------------------------------------


async def test_exercise_removed_from_the_file_is_kept_and_reported(
    db_session: AsyncSession,
) -> None:
    await load_exercises(
        db_session,
        _library(_exercise("old-push-up", harder="push-up"), _exercise("push-up", difficulty=3)),
    )

    report = await load_exercises(db_session, _library(_exercise("push-up", difficulty=3)))

    assert report.not_in_file == ["old-push-up"]
    # Still there for anything that points at it, but no longer part of a ladder.
    assert await _harder_slug(db_session, "old-push-up") is None


async def test_the_ladder_target_of_a_removed_exercise_can_be_reused(
    db_session: AsyncSession,
) -> None:
    # old -> push-up, then old leaves the file and knee -> push-up takes its place.
    await load_exercises(
        db_session,
        _library(_exercise("old-push-up", harder="push-up"), _exercise("push-up", difficulty=3)),
    )

    await load_exercises(
        db_session,
        _library(
            _exercise("knee-push-up", difficulty=1, harder="push-up"),
            _exercise("push-up", difficulty=3),
        ),
    )

    assert await _harder_slug(db_session, "knee-push-up") == "push-up"


# --- alternatives --------------------------------------------------------------------


async def test_alternatives_are_stored_both_ways(db_session: AsyncSession) -> None:
    await load_exercises(
        db_session,
        _library(
            _exercise("push-up", alternatives=["band-chest-press"]), _exercise("band-chest-press")
        ),
    )

    count = await db_session.scalar(select(func.count()).select_from(exercise_alternatives))
    assert count == 2

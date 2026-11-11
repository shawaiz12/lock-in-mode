import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Profile, User
from lock_in_mode_api.models.enums import FitnessLevel, Goal, Location


async def _create_user(session: AsyncSession) -> User:
    user = User()
    session.add(user)
    await session.flush()  # sends the INSERT now, so user.id exists in the DB
    return user


def _valid_profile(user_id: uuid.UUID, **overrides: object) -> Profile:
    """A profile that passes every constraint; tests change one field at a time."""
    fields: dict[str, object] = {
        "user_id": user_id,
        "goal": Goal.STRENGTH,
        "level": FitnessLevel.BEGINNER,
        "location": Location.HOME,
        "days_per_week": 3,
        "minutes_per_session": 20,
    }
    fields.update(overrides)
    return Profile(**fields)


async def test_valid_profile_is_saved(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    db_session.add(_valid_profile(user.id))
    await db_session.flush()  # raises if any constraint fails


@pytest.mark.parametrize("days", [2, 6])
async def test_days_per_week_accepts_boundaries(db_session: AsyncSession, days: int) -> None:
    user = await _create_user(db_session)

    db_session.add(_valid_profile(user.id, days_per_week=days))
    await db_session.flush()


@pytest.mark.parametrize("days", [1, 7])
async def test_days_per_week_rejects_out_of_range(db_session: AsyncSession, days: int) -> None:
    user = await _create_user(db_session)
    db_session.add(_valid_profile(user.id, days_per_week=days))

    with pytest.raises(IntegrityError, match="ck_profiles_days_per_week_range"):
        await db_session.flush()


async def test_minutes_per_session_rejects_unlisted_value(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    db_session.add(_valid_profile(user.id, minutes_per_session=15))

    with pytest.raises(IntegrityError, match="ck_profiles_minutes_per_session_allowed"):
        await db_session.flush()


async def test_profile_requires_existing_user(db_session: AsyncSession) -> None:
    no_such_user = uuid.uuid4()  # random id that isn't in the users table
    db_session.add(_valid_profile(no_such_user))

    with pytest.raises(IntegrityError, match="fk_profiles_user_id_users"):
        await db_session.flush()
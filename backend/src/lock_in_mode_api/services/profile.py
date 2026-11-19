"""Onboarding answers and the safety screen (ADR 0012).

Functions here own the transaction: they commit on success. Routes stay thin.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Profile, User
from lock_in_mode_api.schemas.profile import ProfileWrite, SafetyScreen


class ProfileNotFoundError(Exception):
    """The user hasn't finished onboarding yet. Callers answer 404."""


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    profile = await session.get(Profile, user_id)
    if profile is None:
        raise ProfileNotFoundError
    return profile


async def save_profile(
    session: AsyncSession, user_id: uuid.UUID, answers: ProfileWrite
) -> tuple[Profile, bool]:
    """Create or replace the profile. Returns (profile, created).

    Never touches the safety fields: only the safety screen sets those.
    """
    fields = answers.model_dump()
    profile = await session.get(Profile, user_id)
    created = profile is None
    if profile is None:
        try:
            profile = Profile(user_id=user_id, **fields)
            session.add(profile)
            await session.commit()
        except IntegrityError:
            # Two first saves at once (e.g. a double tap): the other one won.
            # Fall through and update the row it created.
            await session.rollback()
            profile = await session.get(Profile, user_id, populate_existing=True)
            if profile is None:  # not a race after all (e.g. the user was deleted)
                raise
            created = False

    if not created:
        for name, value in fields.items():
            setattr(profile, name, value)
        await session.commit()

    await session.refresh(profile)  # load created_at / updated_at set by the database
    return profile, created


async def record_safety_screen(
    session: AsyncSession, user_id: uuid.UUID, screen: SafetyScreen
) -> Profile:
    """Store only the result. Retaking with all "no" turns low intensity back off."""
    profile = await get_profile(session, user_id)
    profile.needs_low_intensity = screen.any_yes
    profile.safety_screened_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(profile)
    return profile


async def set_display_name(session: AsyncSession, user: User, name: str | None) -> User:
    user.display_name = name
    await session.commit()
    return user

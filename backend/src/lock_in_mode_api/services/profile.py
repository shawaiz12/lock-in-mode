"""Onboarding answers and the safety screen (ADR 0012).

Functions here own the transaction: they commit on success. Routes stay thin.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Plan, Profile, User
from lock_in_mode_api.schemas.profile import ProfileRead, ProfileWrite, SafetyScreen
from lock_in_mode_api.schemas.user import UserUpdate
from lock_in_mode_api.services import events
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.services import sessions as session_service


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

    Never touches the safety fields: only the safety screen sets those. If the new
    answers change the plan, a new block replaces it in the same transaction (ADR 0017).
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
        await _refresh_plan(session, profile)
        await session.commit()

    await session.refresh(profile)  # load created_at / updated_at set by the database
    return profile, created


async def _refresh_plan(session: AsyncSession, profile: Profile) -> None:
    """New answers that change the plan replace it now (ADR 0017). A workout left open
    is finished first with what was logged, so nothing logged is lost (ADR 0018).
    """
    if await plan_service.is_out_of_date(session, profile):
        await session_service.finish_open_session(session, profile.user_id)
        await plan_service.replace_if_answers_changed(session, profile)


async def record_safety_screen(
    session: AsyncSession, user_id: uuid.UUID, screen: SafetyScreen
) -> Profile:
    """Store only the result. Retaking with all "no" turns low intensity back off.

    A changed result changes the plan at once: safety can't wait for the block to end.
    """
    profile = await get_profile(session, user_id)
    first_time = profile.safety_screened_at is None
    profile.needs_low_intensity = screen.any_yes
    profile.safety_screened_at = datetime.now(UTC)
    if first_time:  # profile + safety screen = onboarding done (ADR 0025)
        await events.onboarding_done(session, profile)
    await _refresh_plan(session, profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def profile_read(session: AsyncSession, profile: Profile) -> ProfileRead:
    """The profile as the app reads it, with `pact_due` (ADR 0036): the pact is the last
    onboarding step, so it's due only before the first plan. Someone who already trains
    (maybe offline, mid-workout) never gets sent to it."""
    read = ProfileRead.model_validate(profile)
    if profile.safety_screened_at is None or profile.pact_signed_at is not None:
        return read
    has_plan = await session.scalar(select(exists().where(Plan.user_id == profile.user_id)))
    return read.model_copy(update={"pact_due": not has_plan})


async def sign_pact(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    """The Lock In pact (ADR 0036). Signing again keeps the first date: it's a promise
    made once, and the funnel event is recorded once."""
    profile = await get_profile(session, user_id)
    if profile.pact_signed_at is None:
        profile.pact_signed_at = datetime.now(UTC)
        await events.pact_signed(session, user_id)
        await session.commit()
        await session.refresh(profile)
    return profile


async def update_user(session: AsyncSession, user: User, changes: UserUpdate) -> User:
    """PATCH /me: only the fields sent change. "Share usage data" off erases every past
    funnel event too (ADR 0025). The time zone and the reminder (ADR 0034) are settings of
    the account, not answers: they never change the plan."""
    sent = changes.model_fields_set
    if "time_zone" in sent:
        user.time_zone = changes.time_zone
    if "reminder" in sent:
        reminder = changes.reminder
        if reminder is None:
            if user.reminder_at is not None:
                await events.reminder_off(session, user.id)
            user.reminder_at, user.reminder_days = None, None
        else:
            user.reminder_at, user.reminder_days = reminder.at, reminder.days
            await events.reminder_set(session, user.id, len(reminder.days), reminder.at.hour)
    if "display_name" in sent:
        user.display_name = changes.display_name
    if "share_usage_data" in sent:
        user.share_usage_data = changes.share_usage_data
        if not changes.share_usage_data:
            await events.erase_all(session, user.id)
    await session.commit()
    return user

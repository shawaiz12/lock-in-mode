"""Funnel events (ADR 0025): the server records what happened, in the caller's
transaction, so an action that fails leaves no event. None of these commit.

One function per event, with typed details only: nothing from the safety screen, no
"where it hurts", no free text, no IP or device. A user who switched "Share usage data"
off gets nothing recorded; the check is inside the INSERT itself.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import delete, exists, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Event, Profile, User, WorkoutSession
from lock_in_mode_api.models.enums import EventName, Feedback, FitnessLevel, SessionKind

type SignUpMethod = Literal["guest", "google", "apple"]
type PlanReason = Literal["first", "next_block", "answers_changed"]


async def _record(
    session: AsyncSession, user_id: uuid.UUID, name: EventName, props: dict[str, Any]
) -> None:
    shares = exists().where(User.id == user_id, User.share_usage_data)
    await session.execute(
        insert(Event)
        .from_select(
            ["user_id", "name", "props"],
            select(literal(user_id), literal(name.value), literal(props, JSONB)).where(shares),
        )
        # Only `uq_events_block_complete_once` can clash: a block recorded twice.
        .on_conflict_do_nothing()
    )


async def erase_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    """ "Share usage data" switched off: every past event goes too."""
    await session.execute(delete(Event).where(Event.user_id == user_id))


# --- one function per event ------------------------------------------------------------


async def signed_up(session: AsyncSession, user_id: uuid.UUID, method: SignUpMethod) -> None:
    await _record(session, user_id, EventName.SIGNED_UP, {"method": method})


async def account_linked(
    session: AsyncSession, user_id: uuid.UUID, provider: Literal["google", "apple"]
) -> None:
    await _record(session, user_id, EventName.ACCOUNT_LINKED, {"provider": provider})


async def onboarding_done(session: AsyncSession, profile: Profile) -> None:
    """Profile + first safety screen = ready to train. The safety answers aren't copied."""
    await _record(
        session,
        profile.user_id,
        EventName.ONBOARDING_DONE,
        {
            "goal": profile.goal.value,
            "level": profile.level.value,
            "location": profile.location.value,
            "days_per_week": profile.days_per_week,
            "minutes_per_session": profile.minutes_per_session,
        },
    )


async def plan_started(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    block: int,
    level: FitnessLevel,
    reason: PlanReason,
) -> None:
    await _record(
        session,
        user_id,
        EventName.PLAN_STARTED,
        {"block": block, "level": level.value, "reason": reason},
    )


async def level_up_accepted(
    session: AsyncSession, user_id: uuid.UUID, *, from_level: FitnessLevel, to: FitnessLevel
) -> None:
    await _record(
        session, user_id, EventName.LEVEL_UP_ACCEPTED, {"from": from_level.value, "to": to.value}
    )


async def _sessions(session: AsyncSession, user_id: uuid.UUID, *, finished: bool) -> int:
    query = select(func.count()).where(WorkoutSession.user_id == user_id)
    if finished:
        query = query.where(WorkoutSession.finished_at.is_not(None))
    return await session.scalar(query) or 0


async def workout_started(session: AsyncSession, user_id: uuid.UUID, kind: SessionKind) -> None:
    """Call after the new session is flushed: `number` counts it."""
    number = await _sessions(session, user_id, finished=False)
    await _record(
        session, user_id, EventName.WORKOUT_STARTED, {"number": number, "kind": kind.value}
    )


async def workout_finished(
    session: AsyncSession,
    workout_session: WorkoutSession,
    kind: SessionKind,
) -> None:
    """Call after `finished_at` is flushed: `number` counts this one."""
    user_id = workout_session.user_id
    number = await _sessions(session, user_id, finished=True)
    feedback: Feedback | None = workout_session.feedback
    await _record(
        session,
        user_id,
        EventName.WORKOUT_FINISHED,
        {
            "number": number,
            "kind": kind.value,
            "feedback": None if feedback is None else feedback.value,
            "comeback": workout_session.comeback_id is not None,
        },
    )


async def block_complete(
    session: AsyncSession, user_id: uuid.UUID, *, block: int, level_up_offered: bool
) -> None:
    """Recorded once per block (a unique index), however many requests see it complete."""
    await _record(
        session,
        user_id,
        EventName.BLOCK_COMPLETE,
        {"block": block, "level_up_offered": level_up_offered},
    )


async def comeback_started(
    session: AsyncSession, user_id: uuid.UUID, *, away_days: int, weeks: int
) -> None:
    await _record(
        session, user_id, EventName.COMEBACK_STARTED, {"away_days": away_days, "weeks": weeks}
    )


async def deletion_requested(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _record(session, user_id, EventName.DELETION_REQUESTED, {})


async def deletion_cancelled(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _record(session, user_id, EventName.DELETION_CANCELLED, {})


async def sign_in_offered(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    milestone: Literal["workout_3", "workout_10", "first_block"],
    number: int,
) -> None:
    """The finish screen offered a guest "Protect your progress" (ADR 0026). `number`:
    workouts finished so far."""
    await _record(
        session, user_id, EventName.SIGN_IN_OFFERED, {"milestone": milestone, "number": number}
    )

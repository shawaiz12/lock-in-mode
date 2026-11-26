"""This week and the weekly streak (ADR 0034), from the user's trained workouts.

A trained workout is a finished one with a ticked set (the same rule as the level-up's
good weeks, ADR 0022). Its time is the phone's finish time when it was done offline
(ADR 0033), so a late sync lands in the right week. The rules are in training/week.py.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Profile, SetLog, User, WorkoutSession
from lock_in_mode_api.schemas.week import WeekRead
from lock_in_mode_api.training import week as rules


async def trained_at(session: AsyncSession, user_id: uuid.UUID) -> list[datetime]:
    """When each trained workout was finished."""
    finished = await session.scalars(
        select(WorkoutSession.finished_at).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_not(None),
            exists().where(SetLog.session_id == WorkoutSession.id),
        )
    )
    return [t for t in finished if t is not None]


async def read_week(session: AsyncSession, user_id: uuid.UUID) -> WeekRead:
    zone_name = await session.scalar(select(User.time_zone).where(User.id == user_id))
    zone = ZoneInfo(zone_name or "UTC")
    now: datetime | None = await session.scalar(select(func.now()))
    assert now is not None
    planned = await session.scalar(select(Profile.days_per_week).where(Profile.user_id == user_id))
    week = rules.summarize(
        (rules.local_monday(t, zone) for t in await trained_at(session, user_id)),
        rules.local_monday(now, zone),
    )
    return WeekRead(
        week_start=week.start,
        done=week.done,
        planned=planned,
        keep_at=rules.KEEP_AT,
        kept=week.kept,
        streak=week.streak,
        best_streak=week.best,
        freezes=week.freezes,
        last_week=week.last_week,
    )

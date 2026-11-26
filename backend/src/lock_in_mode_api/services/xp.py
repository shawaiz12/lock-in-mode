"""Awarding XP (ADR 0035): rules in training/xp.py, the ledger in models/xp.py.

`award` runs inside the finish (every way a workout gets finished: the finish button,
starting another workout, changed answers), in the same transaction. Every award is a
row that can exist only once, inserted with ON CONFLICT DO NOTHING: a late or repeated
sync, or the backfill run again, never awards twice.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Profile, SetLog, User, WorkoutSession, XpEvent
from lock_in_mode_api.models.enums import XpSource
from lock_in_mode_api.schemas.xp import XpGained, XpItem, XpLevel
from lock_in_mode_api.services import events
from lock_in_mode_api.training import week as week_rules
from lock_in_mode_api.training import xp as rules

# Shown in this order on the finish screen.
_ORDER = (XpSource.WORKOUT, XpSource.BEST, XpSource.COMEBACK, XpSource.BONUS, XpSource.WEEK)


async def total(session: AsyncSession, user_id: uuid.UUID) -> int:
    xp = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(XpEvent.user_id == user_id)
    )
    return int(xp or 0)


def level_read(xp: int) -> XpLevel:
    level = rules.level_of(xp)
    return XpLevel(total=xp, level=level.level, xp_into=level.xp_into, xp_needed=level.xp_needed)


async def read_xp(session: AsyncSession, user_id: uuid.UUID) -> XpLevel:
    return level_read(await total(session, user_id))


async def _trained_sessions(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[uuid.UUID, datetime, uuid.UUID | None]]:
    """(id, finished_at, comeback_id) of every trained workout, oldest first."""
    rows = await session.execute(
        select(WorkoutSession.id, WorkoutSession.finished_at, WorkoutSession.comeback_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_not(None),
            exists().where(SetLog.session_id == WorkoutSession.id),
        )
        .order_by(WorkoutSession.finished_at, WorkoutSession.id)
    )
    return [(sid, at, comeback) for sid, at, comeback in rows if at is not None]


async def award(
    session: AsyncSession,
    workout_session: WorkoutSession,
    *,
    sets_planned: int,
    new_bests: int,
    bonus_allowed: bool = True,
    announce: bool = True,
) -> XpGained | None:
    """XP for this finished workout. None when nothing was ticked (not a trained workout).

    `bonus_allowed=False` and `announce=False` are for the backfill: no bonus rolls for
    the past, and no level-up events for levels reached long ago."""
    user_id = workout_session.user_id
    finished_at = workout_session.finished_at
    assert finished_at is not None
    sets_done = await session.scalar(
        select(func.count()).where(SetLog.session_id == workout_session.id)
    )
    if not sets_done:
        return None

    zone_name, days = (
        await session.execute(
            select(User.time_zone, Profile.days_per_week)
            .outerjoin(Profile, Profile.user_id == User.id)
            .where(User.id == user_id)
        )
    ).one()
    zone = ZoneInfo(zone_name or "UTC")
    this_week = week_rules.local_monday(finished_at, zone)
    trained = await _trained_sessions(session, user_id)
    mine = [i for i, (sid, _, _) in enumerate(trained) if sid == workout_session.id]
    position = mine[0] if mine else len(trained)
    earlier = trained[:position]
    in_week = [sid for sid, at, _ in trained if week_rules.local_monday(at, zone) == this_week]
    earlier_this_week = sum(
        1 for _, at, _ in earlier if week_rules.local_monday(at, zone) == this_week
    )

    capped = rules.capped(earlier_this_week, days or 7)
    base = 0 if capped else rules.workout_xp(int(sets_done), sets_planned)
    rows: list[tuple[XpSource, int]] = []
    if base:
        rows.append((XpSource.WORKOUT, base))
        if new_bests and rules.bests_xp(new_bests):
            rows.append((XpSource.BEST, rules.bests_xp(new_bests)))
        comeback = workout_session.comeback_id
        if comeback is not None and not any(c == comeback for _, _, c in earlier):
            rows.append((XpSource.COMEBACK, rules.COMEBACK_XP))
        previous = earlier[-1][0] if earlier else None
        previous_had_bonus = previous is not None and bool(
            await session.scalar(
                select(
                    exists().where(XpEvent.session_id == previous, XpEvent.source == XpSource.BONUS)
                )
            )
        )
        if bonus_allowed and rules.gets_bonus(workout_session.id, previous_had_bonus):
            rows.append((XpSource.BONUS, base))

    before = await total(session, user_id)
    awarded: list[tuple[XpSource, int]] = []
    for source, amount in rows:
        inserted = await session.scalar(
            insert(XpEvent)
            .values(user_id=user_id, source=source, amount=amount, session_id=workout_session.id)
            .on_conflict_do_nothing()
            .returning(XpEvent.amount)
        )
        if inserted is not None:
            awarded.append((source, amount))
    if len(in_week) >= week_rules.KEEP_AT:
        inserted = await session.scalar(
            insert(XpEvent)
            .values(
                user_id=user_id, source=XpSource.WEEK, amount=rules.WEEK_XP, week_start=this_week
            )
            .on_conflict_do_nothing()
            .returning(XpEvent.amount)
        )
        if inserted is not None:
            awarded.append((XpSource.WEEK, rules.WEEK_XP))

    after = before + sum(amount for _, amount in awarded)
    before_level, after_level = level_read(before), level_read(after)
    if announce and after_level.level > before_level.level:
        await events.level_up(session, user_id, after_level.level)
    awarded.sort(key=lambda item: _ORDER.index(item[0]))
    return XpGained(
        items=[
            XpItem.model_validate({"source": source.value, "amount": amount})
            for source, amount in awarded
        ],
        gained=after - before,
        bonus=any(source == XpSource.BONUS for source, _ in awarded),
        capped=capped,
        before=before_level,
        after=after_level,
    )

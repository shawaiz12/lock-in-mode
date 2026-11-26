"""XP for workouts trained before XP existed (ADR 0035):

    uv run python -m lock_in_mode_api.xp_backfill

Walks every trained workout without an XP award, oldest first, and awards what it earns:
the workout, its new bests (against earlier workouts only), a comeback, a kept week. No
Locked-in bonus (no rolls for the past) and no level-up events (those levels weren't
reached today). Safe to run again: every award exists at most once, so a second run adds
nothing. The deploy runs it after the migrations.
"""

import asyncio
import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import PlannedWorkoutExercise, SetLog, WorkoutSession, XpEvent
from lock_in_mode_api.services import bests as bests_service
from lock_in_mode_api.services import xp as xp_service


async def _waiting(session: AsyncSession, user_id: uuid.UUID | None = None) -> list[WorkoutSession]:
    """Trained workouts with no XP row yet, oldest first."""
    query = (
        select(WorkoutSession)
        .where(
            WorkoutSession.finished_at.is_not(None),
            exists().where(SetLog.session_id == WorkoutSession.id),
            ~exists().where(XpEvent.session_id == WorkoutSession.id),
        )
        .order_by(WorkoutSession.user_id, WorkoutSession.finished_at, WorkoutSession.id)
    )
    if user_id is not None:
        query = query.where(WorkoutSession.user_id == user_id)
    return list(await session.scalars(query))


async def backfill(session: AsyncSession, user_id: uuid.UUID | None = None) -> int:
    """Award what's missing (for one user, or everyone). Returns the workouts looked at."""
    waiting = await _waiting(session, user_id)
    for workout_session in waiting:
        assert workout_session.finished_at is not None
        planned = await session.scalar(
            select(func.coalesce(func.sum(PlannedWorkoutExercise.sets), 0)).where(
                PlannedWorkoutExercise.planned_workout_id == workout_session.planned_workout_id,
                PlannedWorkoutExercise.swapped_out.is_(False),
            )
        )
        bests = await bests_service.new_bests(
            session, workout_session.user_id, workout_session.id, workout_session.finished_at
        )
        await xp_service.award(
            session,
            workout_session,
            sets_planned=int(planned or 0),
            new_bests=len(bests),
            bonus_allowed=False,
            announce=False,
        )
        await session.commit()
    return len(waiting)


async def _main() -> None:
    from lock_in_mode_api.core.db import SessionLocal, engine

    async with SessionLocal() as session:
        print(f"XP backfill: {await backfill(session)} workouts looked at")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())

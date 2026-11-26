"""The muscle map and the "new bests" count on Home (ADR 0036). Reads only.

The rules are pure (training/muscles.py, training/bests.py); this module feeds them the
ticked sets. "This week" is the same week as `GET /me/week`: Monday to Sunday in the
phone's time zone, by when each workout was finished (the phone's time for a workout done
offline, ADR 0033).
"""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import groupby
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, PlannedWorkoutExercise, SetLog, User, WorkoutSession
from lock_in_mode_api.schemas.muscles import (
    BestsRead,
    MuscleGroupRead,
    MuscleHeadRead,
    MusclesRead,
)
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.services.bests import COUNTED_PARTS
from lock_in_mode_api.training import bests as best_rules
from lock_in_mode_api.training import muscles as rules
from lock_in_mode_api.training import week as week_rules


async def _now_and_zone(session: AsyncSession, user_id: uuid.UUID) -> tuple[datetime, ZoneInfo]:
    zone_name = await session.scalar(select(User.time_zone).where(User.id == user_id))
    now: datetime | None = await session.scalar(select(func.now()))
    assert now is not None
    return now, ZoneInfo(zone_name or "UTC")


async def _next_up(session: AsyncSession, user_id: uuid.UUID) -> tuple[str | None, list[str]]:
    """The next workout's title and the targets of its exercises (not swapped out)."""
    plan = await plan_service.current_plan(session, user_id)
    if plan is None:
        return None, []
    upcoming = (await plan_service.queue_of(session, plan)).upcoming
    if upcoming is None:
        return None, []
    rows = await session.scalars(
        select(Exercise.targets)
        .join(PlannedWorkoutExercise, PlannedWorkoutExercise.exercise_id == Exercise.id)
        .where(
            PlannedWorkoutExercise.planned_workout_id == upcoming.id,
            PlannedWorkoutExercise.part.in_(COUNTED_PARTS),
            PlannedWorkoutExercise.swapped_out.is_(False),
        )
    )
    return upcoming.title, [target for targets in rows for target in targets]


async def read_muscles(session: AsyncSession, user_id: uuid.UUID) -> MusclesRead:
    now, zone = await _now_and_zone(session, user_id)
    this_week = week_rules.local_monday(now, zone)
    rows = await session.execute(
        select(WorkoutSession.finished_at, Exercise.targets)
        .select_from(SetLog)
        .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
        .join(PlannedWorkoutExercise, PlannedWorkoutExercise.id == SetLog.planned_exercise_id)
        .join(Exercise, Exercise.id == PlannedWorkoutExercise.exercise_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_not(None),
            # A cheap first cut (a week plus a day either side for time zones); the exact
            # week is checked below on the user's calendar.
            WorkoutSession.finished_at > now - timedelta(days=9),
            PlannedWorkoutExercise.part.in_(COUNTED_PARTS),
        )
    )
    trained = [
        targets
        for finished_at, targets in rows
        if finished_at is not None and week_rules.local_monday(finished_at, zone) == this_week
    ]
    title, upcoming = await _next_up(session, user_id)
    groups = rules.muscle_map(trained, upcoming)
    return MusclesRead(
        week_start=this_week,
        groups=[
            MuscleGroupRead(
                group=g.group,
                sets=g.sets,
                next_up=g.next_up,
                heads=[
                    MuscleHeadRead(head=h.head, sets=h.sets, next_up=h.next_up) for h in g.heads
                ],
            )
            for g in groups
        ],
        next_workout=title,
    )


async def read_bests(session: AsyncSession, user_id: uuid.UUID) -> BestsRead:
    """Every finished workout's sets, oldest first, through the same rule as the finish
    screen. Grows with history; fine for years of workouts at one query."""
    rows = await session.execute(
        select(
            WorkoutSession.finished_at,
            SetLog.session_id,
            PlannedWorkoutExercise.exercise_id,
            SetLog.weight_kg,
            SetLog.reps,
            SetLog.seconds,
        )
        .join(PlannedWorkoutExercise, PlannedWorkoutExercise.id == SetLog.planned_exercise_id)
        .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_not(None),
            PlannedWorkoutExercise.part.in_(COUNTED_PARTS),
        )
        .order_by(WorkoutSession.finished_at, SetLog.session_id)
    )
    batches: list[list[dict[str, list[best_rules.SetValues]]]] = []
    for _, same_moment in groupby(rows, key=lambda r: r.finished_at):
        workouts: dict[uuid.UUID, dict[str, list[best_rules.SetValues]]] = defaultdict(dict)
        for row in same_moment:
            values = best_rules.SetValues(
                None if row.weight_kg is None else float(row.weight_kg), row.reps, row.seconds
            )
            workouts[row.session_id].setdefault(str(row.exercise_id), []).append(values)
        batches.append(list(workouts.values()))
    return BestsRead(total=best_rules.count_bests(batches))

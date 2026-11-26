"""New personal bests in a finished workout (ADR 0034), against EARLIER workouts only.

Rules in training/bests.py. "Earlier" = finished before this one: a workout synced late
from offline (ADR 0033), or the XP backfill walking history in order (ADR 0035), must not
be compared with workouts done after it.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, PlannedWorkoutExercise, SetLog, WorkoutSession
from lock_in_mode_api.models.enums import WorkoutPart
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.session import NewBest
from lock_in_mode_api.training import bests as rules

COUNTED_PARTS = (WorkoutPart.MAIN, WorkoutPart.FINISHER)


async def new_bests(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, finished_at: datetime
) -> list[NewBest]:
    """Each exercise's best in this workout against its best in every workout finished
    before it."""
    rows = await session.execute(
        select(
            PlannedWorkoutExercise.exercise_id,
            SetLog.session_id,
            WorkoutSession.finished_at,
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
        .order_by(SetLog.logged_at, SetLog.set_number)  # bests in the order they were done
    )
    here: dict[uuid.UUID, list[rules.SetValues]] = {}
    before: dict[uuid.UUID, list[rules.SetValues]] = {}
    order: list[uuid.UUID] = []
    for exercise_id, set_session, set_finished, weight, reps, seconds in rows:
        values = rules.SetValues(None if weight is None else float(weight), reps, seconds)
        if set_session == session_id:
            if exercise_id not in here:
                order.append(exercise_id)
            here.setdefault(exercise_id, []).append(values)
        elif set_finished is not None and set_finished < finished_at:
            before.setdefault(exercise_id, []).append(values)

    found: list[tuple[uuid.UUID, rules.BestKind, float, float]] = []
    for exercise_id in order:
        best = rules.new_best(
            rules.best_of(here[exercise_id]), rules.best_of(before.get(exercise_id, []))
        )
        if best is not None:
            found.append((exercise_id, *best))
    if not found:
        return []
    exercises = {
        e.id: e
        for e in await session.scalars(
            select(Exercise).where(Exercise.id.in_([f[0] for f in found]))
        )
    }
    return [
        NewBest(
            exercise=ExerciseRef.model_validate(exercises[exercise_id]),
            kind=kind,
            value=value,
            previous=previous,
        )
        for exercise_id, kind, value, previous in found
    ]

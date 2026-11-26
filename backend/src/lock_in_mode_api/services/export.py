"""'Download my data' (ADR 0027): everything stored about one person, as one JSON file.

Right of access and portability (GDPR art. 15 and 20): structured, machine-readable, and
readable by a person too, so exercises appear by name and workouts sit inside their plans.
Every table that belongs to a user is in it except `refresh_tokens` (security internals:
only hashes). The Google/Apple account ids aren't in it either: `signed_in_with` says
which providers are linked. A test checks that a new user table can't be left out.

Reads only. Each table is read with a plain SELECT of all its columns, so a column added
later is exported without touching this file.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Comeback,
    Event,
    Exercise,
    ExerciseTarget,
    IntervalStep,
    MovementRung,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    Profile,
    SetLog,
    SwappedOutExercise,
    User,
    WorkoutSession,
    XpEvent,
)

FORMAT = "lock-in-mode-export"
VERSION = 1
# Never exported: security internals and provider account ids.
HIDDEN_USER_COLUMNS = frozenset({"google_sub", "apple_sub"})
NOT_EXPORTED_TABLES = frozenset({"refresh_tokens"})

type Row = dict[str, Any]


def _table(model: type[Any]) -> Table:
    table: Table = model.__table__
    return table


async def _rows(session: AsyncSession, model: type[Any], where: Any, *order: Any) -> list[Row]:
    result = await session.execute(select(_table(model)).where(where).order_by(*order))
    return [dict(row._mapping) for row in result]


def _drop(row: Row, *keys: str) -> Row:
    return {k: v for k, v in row.items() if k not in keys}


def _named(row: Row, names: dict[uuid.UUID, str]) -> Row:
    """`exercise_id` → `exercise`: the exercise's name, as the app shows it."""
    if "exercise_id" not in row:
        return row
    out = {k: v for k, v in row.items() if k != "exercise_id"}
    out["exercise"] = names.get(row["exercise_id"])
    return out


async def build_export(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Everything stored about this user, newest-last within each list."""

    def mine(model: type[Any]) -> Any:
        return model.user_id == user_id

    [user] = await _rows(session, User, User.id == user_id)
    profiles = await _rows(session, Profile, mine(Profile))
    plans = await _rows(session, Plan, mine(Plan), Plan.created_at)
    plan_ids = [p["id"] for p in plans]
    workouts = await _rows(
        session,
        PlannedWorkout,
        PlannedWorkout.plan_id.in_(plan_ids),
        PlannedWorkout.plan_id,
        PlannedWorkout.position,
    )
    planned = await _rows(
        session,
        PlannedWorkoutExercise,
        PlannedWorkoutExercise.planned_workout_id.in_([w["id"] for w in workouts]),
        PlannedWorkoutExercise.planned_workout_id,
        PlannedWorkoutExercise.part,
        PlannedWorkoutExercise.position,
    )
    sessions = await _rows(session, WorkoutSession, mine(WorkoutSession), WorkoutSession.started_at)
    sets = await _rows(
        session,
        SetLog,
        SetLog.session_id.in_([s["id"] for s in sessions]),
        SetLog.logged_at,
        SetLog.set_number,
    )
    rungs = await _rows(session, MovementRung, mine(MovementRung), MovementRung.movement)
    targets = await _rows(session, ExerciseTarget, mine(ExerciseTarget), ExerciseTarget.updated_at)
    steps = await _rows(session, IntervalStep, mine(IntervalStep))
    swapped = await _rows(
        session, SwappedOutExercise, mine(SwappedOutExercise), SwappedOutExercise.created_at
    )
    comebacks = await _rows(session, Comeback, mine(Comeback), Comeback.started_at)
    events = await _rows(session, Event, mine(Event), Event.at, Event.id)
    xp = await _rows(session, XpEvent, mine(XpEvent), XpEvent.created_at, XpEvent.id)

    used = {r["exercise_id"] for r in [*planned, *targets, *swapped]}
    names: dict[uuid.UUID, str] = {
        exercise_id: name
        for exercise_id, name in await session.execute(
            select(Exercise.id, Exercise.name).where(Exercise.id.in_(used))
        )
    }
    planned_names = {p["id"]: names.get(p["exercise_id"]) for p in planned}

    exercises_of: dict[uuid.UUID, list[Row]] = defaultdict(list)
    for row in planned:
        exercises_of[row["planned_workout_id"]].append(
            _named(_drop(row, "planned_workout_id"), names)
        )
    workouts_of: dict[uuid.UUID, list[Row]] = defaultdict(list)
    for row in workouts:
        workouts_of[row["plan_id"]].append(
            {**_drop(row, "plan_id"), "exercises": exercises_of[row["id"]]}
        )
    sets_of: dict[uuid.UUID, list[Row]] = defaultdict(list)
    for row in sets:
        sets_of[row["session_id"]].append(
            {**_drop(row, "session_id"), "exercise": planned_names.get(row["planned_exercise_id"])}
        )

    now: datetime | None = await session.scalar(select(func.now()))
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": now,
        "account": {
            **_drop(user, *HIDDEN_USER_COLUMNS),
            "signed_in_with": [
                name
                for name, column in (("google", "google_sub"), ("apple", "apple_sub"))
                if user[column] is not None
            ],
        },
        "profile": _drop(profiles[0], "user_id") if profiles else None,
        "plans": [{**_drop(p, "user_id"), "workouts": workouts_of[p["id"]]} for p in plans],
        "workout_sessions": [{**_drop(s, "user_id"), "sets": sets_of[s["id"]]} for s in sessions],
        "strength_test": [_drop(r, "user_id") for r in rungs],
        "exercise_progress": [_named(_drop(t, "user_id"), names) for t in targets],
        "interval_progress": _drop(steps[0], "user_id") if steps else None,
        "swapped_out_exercises": [_named(_drop(s, "user_id"), names) for s in swapped],
        "comebacks": [_drop(c, "user_id") for c in comebacks],
        "usage_events": [_drop(e, "user_id") for e in events],
        "xp": [_drop(x, "user_id") for x in xp],
    }

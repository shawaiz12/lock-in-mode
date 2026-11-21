"""Doing workouts: start, tick sets, finish, the strength-test placement (ADR 0018) and,
on finishing, progression (ADR 0019).

Functions that change data own the transaction and commit, except `finish_open_session`,
which joins the caller's (the profile service's: answers changed, plan about to be
replaced).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lock_in_mode_api.models import (
    Exercise,
    MovementRung,
    PlannedWorkoutExercise,
    SetLog,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import Feedback, WorkoutPart, WorkoutStatus
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.session import (
    Placement,
    Progress,
    SessionRead,
    SessionResult,
    SetLogRead,
    SetLogWrite,
)
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.services import progress as progress_service
from lock_in_mode_api.training.placement import placed_exercise


class SessionNotFoundError(Exception):
    """No such session for this user (or no open one). Callers answer 404."""


class SessionFinishedError(Exception):
    """The session is finished: no more sets, no second finish. Callers answer 409."""


class PlannedExerciseNotFoundError(Exception):
    """That exercise isn't part of this session's workout. Callers answer 404."""


# --- reading --------------------------------------------------------------------------


async def _open_session(session: AsyncSession, user_id: uuid.UUID) -> WorkoutSession | None:
    return await session.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user_id, WorkoutSession.finished_at.is_(None))
        .options(selectinload(WorkoutSession.sets))
        .execution_options(populate_existing=True)
    )


async def _load(session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession:
    found = await session.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.id == session_id, WorkoutSession.user_id == user_id)
        .options(selectinload(WorkoutSession.sets))
        .execution_options(populate_existing=True)
        .with_for_update(of=WorkoutSession)  # finishing twice at once: the second waits
    )
    if found is None:
        raise SessionNotFoundError
    return found


def _read(workout_session: WorkoutSession) -> SessionRead:
    return SessionRead(
        id=workout_session.id,
        workout_id=workout_session.planned_workout_id,
        started_at=workout_session.started_at,
        finished_at=workout_session.finished_at,
        feedback=workout_session.feedback,
        sets=[SetLogRead.model_validate(s) for s in workout_session.sets],
    )


async def get_open_session(session: AsyncSession, user_id: uuid.UUID) -> SessionRead:
    """The app asks on launch: an open session means "Continue or finish now?"."""
    found = await _open_session(session, user_id)
    if found is None:
        raise SessionNotFoundError
    return _read(found)


# --- finishing (and placing from the strength test) ---------------------------------------


async def _place_from_test(
    session: AsyncSession, workout_session: WorkoutSession, main: list[PlannedWorkoutExercise]
) -> list[Placement]:
    """Open test sets (KB section 2) → a rung per movement. The caller rebuilds what's left.

    Weighted tests keep their reps and place nothing: the weight logged becomes "last
    time" and pre-fills the next workout. A test with no logged set places nothing.
    """
    best: dict[uuid.UUID, int] = {}
    for logged in workout_session.sets:
        value = logged.reps if logged.reps is not None else logged.seconds
        if value is not None:
            best[logged.planned_exercise_id] = max(value, best.get(logged.planned_exercise_id, 0))

    placements: list[Placement] = []
    for row in main:
        if not row.is_test or row.reps_min is not None or row.id not in best:
            continue
        movement = row.exercise.movement_slot
        slug = placed_exercise(movement, best[row.id])
        rung = (
            None
            if slug is None
            else await session.scalar(select(Exercise).where(Exercise.slug == slug))
        )
        if rung is None:
            continue
        await session.execute(
            insert(MovementRung)
            .values(
                user_id=workout_session.user_id,
                movement=movement,
                difficulty=rung.difficulty,
                result=best[row.id],
            )
            .on_conflict_do_update(
                index_elements=[MovementRung.user_id, MovementRung.movement],
                set_={"difficulty": rung.difficulty, "result": best[row.id]},
            )
        )
        placements.append(
            Placement(
                movement=movement,
                result=best[row.id],
                unit="seconds" if row.exercise.is_timed else "reps",
                exercise=ExerciseRef.model_validate(rung),
            )
        )
    return placements


@dataclass(frozen=True)
class _Closed:
    placements: list[Placement]
    progress: list[Progress]
    recovery_earned: bool


async def _close(
    session: AsyncSession, workout_session: WorkoutSession, feedback: Feedback | None
) -> _Closed:
    """Finish with whatever was logged: half a workout still counts (ADR 0018).

    Then, in order: progression and the test placement (both may move rungs), one
    rebuild of the rest of the block if they did, and the early recovery week, which
    must come after the rebuild because it changes which workouts are pending.
    """
    now = datetime.now(UTC)
    workout_session.finished_at = now
    workout_session.feedback = feedback
    workout = await plan_service.load_workout(
        session, workout_session.user_id, workout_session.planned_workout_id, lock=True
    )
    workout.status = WorkoutStatus.DONE
    workout.status_changed_at = now
    plan_id, week = workout.plan_id, workout.week
    main = [row for row in workout.exercises if row.part == WorkoutPart.MAIN]
    await session.flush()  # this feedback counts in the streak and the week below

    outcome = await progress_service.after_finish(session, workout_session, workout, main)
    placements = await _place_from_test(session, workout_session, main)
    if placements or outcome.rungs_changed:
        await session.flush()
        await plan_service.rebuild_pending(session, workout_session.user_id)
    recovery = await progress_service.bring_recovery_forward(
        session, workout_session, plan_id, week
    )
    return _Closed(placements, outcome.progress, recovery)


async def finish_open_session(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Close the open session, if any (no feedback). The caller commits."""
    found = await _open_session(session, user_id)
    if found is not None:
        await _close(session, found, None)
        await session.flush()


async def finish_session(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, feedback: Feedback | None
) -> SessionResult:
    workout_session = await _load(session, user_id, session_id)
    if workout_session.finished_at is not None:
        raise SessionFinishedError
    closed = await _close(session, workout_session, feedback)
    await session.commit()
    plan = await plan_service.get_current_plan(session, user_id)
    return SessionResult(
        **_read(await _load(session, user_id, session_id)).model_dump(),
        placements=closed.placements,
        progress=closed.progress,
        recovery_earned=closed.recovery_earned,
        next_workout_id=plan.next_workout_id,
        block_complete=plan.block_complete,
    )


# --- starting -----------------------------------------------------------------------------


async def start_session(
    session: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID
) -> tuple[SessionRead, bool]:
    """Start the next workout, or continue it. Returns (session, created).

    If another workout is still open, it's finished first with what was logged, so the
    queue moves on and this one can become the next.
    """
    await plan_service.load_workout(session, user_id, workout_id)  # 404 if not theirs
    open_session = await _open_session(session, user_id)
    if open_session is not None and open_session.planned_workout_id == workout_id:
        return _read(open_session), False  # "Continue"
    if open_session is not None:
        await _close(session, open_session, None)
        await session.flush()

    plan = await plan_service.current_plan(session, user_id)
    upcoming = None if plan is None else plan_service.next_workout(plan)
    if upcoming is None or upcoming.id != workout_id:
        await session.rollback()  # don't keep the half-done finish above
        raise plan_service.NotNextWorkoutError

    session.add(WorkoutSession(user_id=user_id, planned_workout_id=workout_id))
    try:
        await session.commit()
    except IntegrityError:
        # A double tap: the first request opened it. Hand back that one.
        await session.rollback()
        open_session = await _open_session(session, user_id)
        if open_session is None or open_session.planned_workout_id != workout_id:
            raise
        return _read(open_session), False
    started = await _open_session(session, user_id)
    assert started is not None
    return _read(started), True


# --- logging sets -------------------------------------------------------------------------


async def _check_exercise(
    session: AsyncSession, workout_session: WorkoutSession, planned_exercise_id: uuid.UUID
) -> None:
    if workout_session.finished_at is not None:
        raise SessionFinishedError
    row = await session.get(PlannedWorkoutExercise, planned_exercise_id)
    if row is None or row.planned_workout_id != workout_session.planned_workout_id:
        raise PlannedExerciseNotFoundError


async def log_set(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    planned_exercise_id: uuid.UUID,
    set_number: int,
    values: SetLogWrite,
) -> SetLogRead:
    """Tick a set. Ticking it again replaces it: an upsert on (session, exercise, set)."""
    workout_session = await _load(session, user_id, session_id)
    await _check_exercise(session, workout_session, planned_exercise_id)
    fields = values.model_dump()
    await session.execute(
        insert(SetLog)
        .values(
            session_id=session_id,
            planned_exercise_id=planned_exercise_id,
            set_number=set_number,
            **fields,
        )
        .on_conflict_do_update(
            constraint="uq_set_logs_session_exercise_set",
            set_={**fields, "logged_at": datetime.now(UTC)},
        )
    )
    await session.commit()
    return SetLogRead(planned_exercise_id=planned_exercise_id, set_number=set_number, **fields)


async def delete_set(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    planned_exercise_id: uuid.UUID,
    set_number: int,
) -> None:
    """Untick a set. Unticking one that isn't there is fine: the result is the same."""
    workout_session = await _load(session, user_id, session_id)
    await _check_exercise(session, workout_session, planned_exercise_id)
    await session.execute(
        delete(SetLog).where(
            SetLog.session_id == session_id,
            SetLog.planned_exercise_id == planned_exercise_id,
            SetLog.set_number == set_number,
        )
    )
    await session.commit()

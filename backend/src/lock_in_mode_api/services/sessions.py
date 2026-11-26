"""Doing workouts: start, tick sets, finish, the strength-test placement (ADR 0018) and,
on finishing, progression (ADR 0019). Starting the first workout after a break saves the
comeback and links the session to it (ADR 0021).

A workout done offline arrives later with the phone's times (ADR 0033). Each one is kept
in order by the database (`_kept_between`): never before what came before it, never after
the database's now. A phone clock that is wrong can't put a workout in the future or
before the last one.

Functions that change data own the transaction and commit, except `finish_open_session`,
which joins the caller's (the profile service's: answers changed, plan about to be
replaced).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, DateTime, ScalarSelect, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lock_in_mode_api.models import (
    Exercise,
    MovementRung,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    SetLog,
    User,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import Feedback, WorkoutPart, WorkoutStatus
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.session import (
    IntervalProgress,
    NewBest,
    Placement,
    Progress,
    SessionRead,
    SessionResult,
    SetLogRead,
    SetLogWrite,
)
from lock_in_mode_api.schemas.xp import XpGained
from lock_in_mode_api.services import bests as bests_service
from lock_in_mode_api.services import comeback as comeback_service
from lock_in_mode_api.services import events, sign_in_offer
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.services import progress as progress_service
from lock_in_mode_api.services import week as week_service
from lock_in_mode_api.services import xp as xp_service
from lock_in_mode_api.training.placement import placed_exercise


class SessionNotFoundError(Exception):
    """No such session for this user (or no open one). Callers answer 404."""


class SessionFinishedError(Exception):
    """The session is finished: no more sets, no second finish. Callers answer 409."""


class PlannedExerciseNotFoundError(Exception):
    """That exercise isn't part of this session's workout. Callers answer 404."""


# --- the phone's times (ADR 0033) ------------------------------------------------------


type Floor = ColumnElement[Any] | ScalarSelect[Any] | datetime


async def _kept_between(session: AsyncSession, at: datetime, floors: Sequence[Floor]) -> datetime:
    """`at`, moved up to the latest floor and down to the database's now.

    Worked out by the database: its `now()` is the one server clock these times are ever
    compared with. A floor that is NULL (no earlier workout yet) is left out by GREATEST.
    """
    stamp = DateTime(timezone=True)
    lowest = [literal(f, stamp) if isinstance(f, datetime) else f for f in floors]
    kept: datetime | None = await session.scalar(
        select(func.least(func.greatest(literal(at, stamp), *lowest), func.now()))
    )
    assert kept is not None
    return kept


async def _start_time(
    session: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID, at: datetime
) -> datetime:
    """When an offline start really happened: not before the plan existed or the last
    finished workout (which is never before its own sets), so workouts stay in the order
    they were done."""
    plan_made = (
        select(Plan.created_at)
        .join(PlannedWorkout, PlannedWorkout.plan_id == Plan.id)
        .where(PlannedWorkout.id == workout_id)
        .scalar_subquery()
    )
    last_finish = (
        select(func.max(WorkoutSession.finished_at))
        .where(WorkoutSession.user_id == user_id)
        .scalar_subquery()
    )
    return await _kept_between(session, at, [plan_made, last_finish])


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
    intervals: IntervalProgress | None
    recovery_earned: bool
    new_bests: list[NewBest]
    xp: XpGained | None


async def _close(
    session: AsyncSession,
    workout_session: WorkoutSession,
    feedback: Feedback | None,
    finished_at: datetime | None = None,
) -> _Closed:
    """Finish with whatever was logged: half a workout still counts (ADR 0018).

    Then, in order: progression and the test placement (both may move rungs), one
    rebuild of the rest of the block if they did, and the early recovery week, which
    must come after the rebuild because it changes which workouts are pending.

    `finished_at`: the phone's time for a workout finished offline (ADR 0033), kept
    after its start and its last ticked set.
    """
    if finished_at is None:
        now = datetime.now(UTC)
    else:
        last_set = (
            select(func.max(SetLog.logged_at))
            .where(SetLog.session_id == workout_session.id)
            .scalar_subquery()
        )
        now = await _kept_between(session, finished_at, [workout_session.started_at, last_set])
    workout_session.finished_at = now
    workout_session.feedback = feedback
    workout = await plan_service.load_workout(
        session, workout_session.user_id, workout_session.planned_workout_id, lock=True
    )
    workout.status = WorkoutStatus.DONE
    workout.status_changed_at = now
    plan_id, week = workout.plan_id, workout.week
    main = [row for row in workout.exercises if row.part == WorkoutPart.MAIN]
    sets_planned = sum(row.sets for row in workout.exercises if not row.swapped_out)
    await session.flush()  # this feedback counts in the streak and the week below

    await events.workout_finished(session, workout_session, workout.kind)
    outcome = await progress_service.after_finish(session, workout_session, workout, main)
    placements = await _place_from_test(session, workout_session, main)
    if placements or outcome.rungs_changed:
        await session.flush()
        await plan_service.rebuild_pending(session, workout_session.user_id)
    recovery = await progress_service.bring_recovery_forward(
        session, workout_session, plan_id, week
    )
    # New bests and XP (ADR 0034, 0035), read before the comeback is closed below.
    bests = await bests_service.new_bests(session, workout_session.user_id, workout_session.id, now)
    xp = await xp_service.award(
        session, workout_session, sets_planned=sets_planned, new_bests=len(bests)
    )
    await comeback_service.after_finish(session, workout_session)
    return _Closed(placements, outcome.progress, outcome.intervals, recovery, bests, xp)


async def finish_open_session(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Close the open session, if any (no feedback). The caller commits."""
    found = await _open_session(session, user_id)
    if found is not None:
        await _close(session, found, None)
        await session.flush()


async def finish_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    feedback: Feedback | None,
    finished_at: datetime | None = None,
) -> SessionResult:
    workout_session = await _load(session, user_id, session_id)
    if workout_session.finished_at is not None:
        raise SessionFinishedError
    closed = await _close(session, workout_session, feedback, finished_at)
    await session.flush()
    block_complete = await plan_service.note_block_complete(session, user_id)
    # Guests at their 3rd or 10th workout or first finished block (ADR 0026).
    offer = await sign_in_offer.offer_after_finish(session, user_id, block_complete=block_complete)
    await session.commit()
    plan = await plan_service.get_current_plan(session, user_id)
    trained = len(await week_service.trained_at(session, user_id))
    has_reminder = await session.scalar(
        select(User.reminder_at.is_not(None)).where(User.id == user_id)
    )
    return SessionResult(
        **_read(await _load(session, user_id, session_id)).model_dump(),
        placements=closed.placements,
        progress=closed.progress,
        intervals=closed.intervals,
        recovery_earned=closed.recovery_earned,
        next_workout_id=plan.next_workout_id,
        block_complete=plan.block_complete,
        sign_in_offer=offer,
        new_bests=closed.new_bests,
        xp=closed.xp,
        week=await week_service.read_week(session, user_id),
        offer_reminder=trained == 1 and not has_reminder,
    )


# --- starting -----------------------------------------------------------------------------


async def start_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
    started_at: datetime | None = None,
) -> tuple[SessionRead, bool]:
    """Start the next workout, or continue it. Returns (session, created).

    If another workout is still open, it's finished first with what was logged, so the
    queue moves on and this one can become the next.

    `started_at`: the phone's time for a workout started offline (ADR 0033). The queue
    and a break are then judged as of that moment. Continuing keeps the first start.
    """
    await plan_service.load_workout(session, user_id, workout_id)  # 404 if not theirs
    open_session = await _open_session(session, user_id)
    if open_session is not None and open_session.planned_workout_id == workout_id:
        if await _continue_after_break(session, user_id, open_session):
            open_session = await _open_session(session, user_id)
            assert open_session is not None
        return _read(open_session), False  # "Continue"
    if open_session is not None:
        await _close(session, open_session, None)
        await session.flush()

    at = None if started_at is None else await _start_time(session, user_id, workout_id, started_at)
    plan = await plan_service.current_plan(session, user_id)
    queue = None if plan is None else await plan_service.queue_of(session, plan, now=at)
    if plan is None or queue is None or queue.upcoming is None or queue.upcoming.id != workout_id:
        await session.rollback()  # don't keep the half-done finish above
        raise plan_service.NotNextWorkoutError

    new_session = WorkoutSession(user_id=user_id, planned_workout_id=workout_id)
    if at is not None:
        new_session.started_at = at
    try:
        await _join_comeback(session, plan, queue, new_session)
        session.add(new_session)
        await session.flush()  # a double tap fails here; then counted below
        await events.workout_started(session, user_id, queue.upcoming.kind)
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


async def _join_comeback(
    session: AsyncSession,
    plan: Plan,
    queue: plan_service.Queue,
    workout_session: WorkoutSession,
) -> None:
    """Back after a break (ADR 0021): save a due comeback (dropping a recovery week the
    break replaces) and link this session to it, so the workout keeps its eased numbers.
    The caller commits."""
    comeback = queue.comeback
    if comeback is None:
        return
    saved = comeback.saved
    if saved is None:
        saved = await comeback_service.start(session, plan.user_id, comeback)
        plan_service.drop_recovery(plan, queue)
    eased = queue.weeks.get(workout_session.planned_workout_id)
    if eased is not None:
        workout_session.comeback_id = saved.id
        workout_session.comeback_week = eased[1]


async def _continue_after_break(
    session: AsyncSession, user_id: uuid.UUID, open_session: WorkoutSession
) -> bool:
    """ "Continue" on a workout left open since before a break: it joins the comeback,
    so the sets left are eased. Returns True if anything was written (reload it)."""
    plan = await plan_service.current_plan(session, user_id)
    if plan is None:
        return False
    queue = await plan_service.queue_of(session, plan)
    if queue.comeback is None or not queue.comeback.due:
        return False
    try:
        await _join_comeback(session, plan, queue, open_session)
        await session.commit()
    except IntegrityError:
        await session.rollback()  # a double tap saved it first: that one stands
    return True


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
    """Tick a set. Ticking it again replaces it: an upsert on (session, exercise, set).

    `logged_at` (ADR 0033): the phone's time, kept between the workout's start and now.
    Without it, the server's time.
    """
    workout_session = await _load(session, user_id, session_id)
    await _check_exercise(session, workout_session, planned_exercise_id)
    fields = values.model_dump(exclude={"logged_at"})
    phone = values.logged_at
    when = (
        None if phone is None else await _kept_between(session, phone, [workout_session.started_at])
    )
    await session.execute(
        insert(SetLog)
        .values(
            session_id=session_id,
            planned_exercise_id=planned_exercise_id,
            set_number=set_number,
            **fields,
            **({} if when is None else {"logged_at": when}),
        )
        .on_conflict_do_update(
            constraint="uq_set_logs_session_exercise_set",
            set_={**fields, "logged_at": datetime.now(UTC) if when is None else when},
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

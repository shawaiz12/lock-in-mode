"""Doing a workout: start (or continue), tick sets, finish with feedback (ADR 0018).

The player calls these while the user trains. Every set is one small request, so a
dropped connection loses one tick at most, and ticking the same set again is safe.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from lock_in_mode_api.api.deps import CurrentUser, DbSession
from lock_in_mode_api.api.errors import (
    NotFound,
    NotNextWorkout,
    SessionFinished,
    SessionNotFound,
)
from lock_in_mode_api.schemas.session import (
    SessionFinish,
    SessionRead,
    SessionResult,
    SessionStart,
    SetLogRead,
    SetLogWrite,
)
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.services import sessions as session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])

type SetNumber = Annotated[int, Path(ge=1, le=20)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": SessionRead, "description": "Continued"}},
)
async def start_session(
    user: CurrentUser, body: SessionStart, session: DbSession, response: Response
) -> SessionRead:
    """ "Lock In: start workout". 201 when started, 200 when continuing the open one.

    Only the next workout can be started. A different workout left open is finished
    first with what was logged (half counts), so the queue moves on.
    """
    try:
        started, created = await session_service.start_session(session, user.id, body.workout_id)
    except plan_service.WorkoutNotFoundError as exc:
        raise NotFound("No workout with this id") from exc
    except plan_service.NotNextWorkoutError as exc:
        raise NotNextWorkout("Only the next workout in the queue can be started") from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return started


@router.get("/current")
async def read_open_session(user: CurrentUser, session: DbSession) -> SessionRead:
    """The open session, if any: on app start, offer "Continue" or "Finish now"."""
    try:
        return await session_service.get_open_session(session, user.id)
    except session_service.SessionNotFoundError as exc:
        raise SessionNotFound("No workout in progress") from exc


@router.put("/{session_id}/sets/{planned_exercise_id}/{set_number}")
async def log_set(
    user: CurrentUser,
    session_id: uuid.UUID,
    planned_exercise_id: uuid.UUID,
    set_number: SetNumber,
    body: SetLogWrite,
    session: DbSession,
) -> SetLogRead:
    """Tick a set: reps and/or seconds, plus the weight for weighted moves.

    PUT, because sending it twice gives the same result: the second replaces the first.
    """
    try:
        return await session_service.log_set(
            session, user.id, session_id, planned_exercise_id, set_number, body
        )
    except session_service.SessionNotFoundError as exc:
        raise SessionNotFound("No session with this id") from exc
    except session_service.PlannedExerciseNotFoundError as exc:
        raise NotFound("That exercise isn't in this workout") from exc
    except session_service.SessionFinishedError as exc:
        raise SessionFinished("This workout is finished") from exc


@router.delete(
    "/{session_id}/sets/{planned_exercise_id}/{set_number}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_set(
    user: CurrentUser,
    session_id: uuid.UUID,
    planned_exercise_id: uuid.UUID,
    set_number: SetNumber,
    session: DbSession,
) -> None:
    """Untick a set (a mis-tap)."""
    try:
        await session_service.delete_set(
            session, user.id, session_id, planned_exercise_id, set_number
        )
    except session_service.SessionNotFoundError as exc:
        raise SessionNotFound("No session with this id") from exc
    except session_service.PlannedExerciseNotFoundError as exc:
        raise NotFound("That exercise isn't in this workout") from exc
    except session_service.SessionFinishedError as exc:
        raise SessionFinished("This workout is finished") from exc


@router.post("/{session_id}/finish")
async def finish_session(
    user: CurrentUser, session_id: uuid.UUID, body: SessionFinish, session: DbSession
) -> SessionResult:
    """Finish, early or not: it counts either way. Feedback is one optional tap.

    If this was the strength test, `placements` says where each movement starts
    ("3 push-ups → knee push-ups") and the rest of the block already uses it.
    """
    try:
        return await session_service.finish_session(session, user.id, session_id, body.feedback)
    except session_service.SessionNotFoundError as exc:
        raise SessionNotFound("No session with this id") from exc
    except session_service.SessionFinishedError as exc:
        raise SessionFinished("This workout is already finished") from exc

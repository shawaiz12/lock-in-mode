"""Swapping exercises: "this hurts, swap it", "show another", and the swapped-out list
(ADR 0020, KB section 11)."""

import uuid

from fastapi import APIRouter, status

from lock_in_mode_api.api.deps import CurrentUser, DbSession
from lock_in_mode_api.api.errors import ExerciseChanged, NoOtherExercise, NotFound, NotNextWorkout
from lock_in_mode_api.schemas.swap import (
    SwappedOutRead,
    SwapRequest,
    SwapResult,
    WhereItHurts,
    WhereResult,
)
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.services import swaps as swap_service

router = APIRouter(tags=["swaps"])


@router.post("/workouts/{workout_id}/exercises/{planned_exercise_id}/swap")
async def swap_exercise(
    user: CurrentUser,
    workout_id: uuid.UUID,
    planned_exercise_id: uuid.UUID,
    body: SwapRequest,
    session: DbSession,
) -> SwapResult:
    """Swap one exercise of the next workout, before or during it. Any part: warm-up,
    main, finisher, cool-down.

    - `hurts`: swapped out for good (undo: `DELETE /me/swapped-out/{exercise_id}`). Today
      gets the best safe stand-in, same or easier; the rest of the block is rebuilt
      without it. Then the app may ask "Where does it hurt?" (`PATCH /me/swapped-out/...`).
    - `another`: a different pick for today only. Tap again to see the next one.

    Sets already done stay with the old exercise; the stand-in asks for the sets left.
    Nothing safe left: `left_out: true`, the slot is left out.
    """
    try:
        return await swap_service.swap(
            session, user.id, workout_id, planned_exercise_id, body.exercise_id, body.reason
        )
    except (plan_service.WorkoutNotFoundError, swap_service.PlannedExerciseNotFoundError) as exc:
        raise NotFound("No such exercise in this workout") from exc
    except plan_service.NotNextWorkoutError as exc:
        raise NotNextWorkout("Only the next workout can be changed") from exc
    except swap_service.ExerciseChangedError as exc:
        raise ExerciseChanged("This exercise was already swapped: refresh the workout") from exc
    except swap_service.NoOtherExerciseError as exc:
        raise NoOtherExercise("Nothing else safe does this job for you") from exc


@router.get("/me/swapped-out")
async def list_swapped_out(user: CurrentUser, session: DbSession) -> list[SwappedOutRead]:
    """Exercises swapped out because they hurt, newest first. Each can be brought back."""
    return await swap_service.list_swapped_out(session, user.id)


@router.patch("/me/swapped-out/{exercise_id}")
async def say_where_it_hurts(
    user: CurrentUser, exercise_id: uuid.UUID, body: WhereItHurts, session: DbSession
) -> WhereResult:
    """The optional "Where does it hurt?" after a swap. May suggest a profile limit."""
    try:
        return await swap_service.set_where(session, user.id, exercise_id, body.body_area)
    except swap_service.SwapNotFoundError as exc:
        raise NotFound("This exercise isn't swapped out") from exc


@router.delete("/me/swapped-out/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT)
async def bring_back(user: CurrentUser, exercise_id: uuid.UUID, session: DbSession) -> None:
    """ "Bring it back": the plan may pick it again, from the rest of this block on."""
    try:
        await swap_service.bring_back(session, user.id, exercise_id)
    except swap_service.SwapNotFoundError as exc:
        raise NotFound("This exercise isn't swapped out") from exc

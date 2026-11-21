"""Plans and the "next workout" queue (ADR 0014, ADR 0017).

The home screen calls `GET /plans/current/next`. There's no "missed" anything: the
queue only moves when a workout is finished (sessions, next stage) or skipped.
"""

import uuid

from fastapi import APIRouter, Request, Response, status

from lock_in_mode_api.api.caching import NOT_MODIFIED_DOC, json_with_etag
from lock_in_mode_api.api.deps import CurrentUser, DbSession
from lock_in_mode_api.api.errors import (
    BlockComplete,
    NotFound,
    NotNextWorkout,
    PlanInProgress,
    PlanNotFound,
    ProfileNotFound,
    SafetyScreenRequired,
)
from lock_in_mode_api.schemas.plan import PlanRead, WorkoutDetail
from lock_in_mode_api.services import plans as plan_service

router = APIRouter(tags=["plans"])


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def start_plan(user: CurrentUser, session: DbSession) -> PlanRead:
    """Build and save a training block: 4 build-up weeks and a recovery week.

    Call once after onboarding and the safety screen, then again from the
    "Block complete!" screen. Changing the profile replaces the plan by itself.
    """
    try:
        return await plan_service.start_plan(session, user.id)
    except plan_service.ProfileRequiredError as exc:
        raise ProfileNotFound("Finish onboarding first") from exc
    except plan_service.SafetyScreenRequiredError as exc:
        raise SafetyScreenRequired("Take the safety screen before the first plan") from exc
    except plan_service.PlanInProgressError as exc:
        raise PlanInProgress("Finish or skip the rest of this block first") from exc


@router.get("/plans/current", response_model=PlanRead, responses=NOT_MODIFIED_DOC)
async def read_current_plan(request: Request, user: CurrentUser, session: DbSession) -> Response:
    """The current block: why it looks like this, suggested days, and the whole queue."""
    try:
        plan = await plan_service.get_current_plan(session, user.id)
    except plan_service.PlanNotFoundError as exc:
        raise PlanNotFound("No plan yet: POST /plans after the safety screen") from exc
    return json_with_etag(request, plan)


@router.get("/plans/current/next", response_model=WorkoutDetail, responses=NOT_MODIFIED_DOC)
async def read_next_workout(request: Request, user: CurrentUser, session: DbSession) -> Response:
    """The next workout in full: what the home screen shows and the player runs."""
    try:
        workout = await plan_service.get_next_workout(session, user.id)
    except plan_service.PlanNotFoundError as exc:
        raise PlanNotFound("No plan yet: POST /plans after the safety screen") from exc
    except plan_service.BlockCompleteError as exc:
        raise BlockComplete("Every workout of this block is done or skipped") from exc
    return json_with_etag(request, workout)


@router.get("/workouts/{workout_id}", response_model=WorkoutDetail, responses=NOT_MODIFIED_DOC)
async def read_workout(
    request: Request, user: CurrentUser, workout_id: uuid.UUID, session: DbSession
) -> Response:
    """Any of the user's workouts, including those in old plans."""
    try:
        workout = await plan_service.get_workout(session, user.id, workout_id)
    except plan_service.WorkoutNotFoundError as exc:
        raise NotFound("No workout with this id") from exc
    return json_with_etag(request, workout)


@router.post("/workouts/{workout_id}/skip")
async def skip_workout(user: CurrentUser, workout_id: uuid.UUID, session: DbSession) -> PlanRead:
    """Skip the next workout: no penalty, the queue moves on. Returns the updated plan.

    Skipping the strength test moves it to the next strength workout.
    """
    try:
        return await plan_service.skip_workout(session, user.id, workout_id)
    except plan_service.WorkoutNotFoundError as exc:
        raise NotFound("No workout with this id") from exc
    except plan_service.NotNextWorkoutError as exc:
        raise NotNextWorkout("Only the next workout in the queue can be skipped") from exc

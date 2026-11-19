import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from lock_in_mode_api.api.caching import NOT_MODIFIED_DOC, json_with_etag
from lock_in_mode_api.api.deps import CurrentUser, DbSession
from lock_in_mode_api.api.errors import NotFound, ProfileNotFound
from lock_in_mode_api.schemas.exercise import ExerciseDetail, ExerciseFilters, ExercisePage
from lock_in_mode_api.services import exercises as exercise_service

router = APIRouter(prefix="/exercises", tags=["exercises"])

# Both endpoints send an ETag; send it back in If-None-Match to get an empty 304 when
# nothing changed (ADR 0013). They return a Response, so `response_model` documents the body.


@router.get("", response_model=ExercisePage, responses=NOT_MODIFIED_DOC)
async def list_exercises(
    request: Request,
    user: CurrentUser,
    filters: Annotated[ExerciseFilters, Query()],
    session: DbSession,
) -> Response:
    """The exercise library, 50 per page, sorted by name.

    `for_me=true` keeps only what this user's location and equipment allow. Every item
    carries `cautions` when the user has a profile: show them as warnings.
    """
    try:
        page = await exercise_service.list_exercises(session, user.id, filters)
    except exercise_service.ProfileRequiredError as exc:
        raise ProfileNotFound("Finish onboarding to see exercises for you") from exc
    return json_with_etag(request, page)


@router.get("/{exercise_id}", response_model=ExerciseDetail, responses=NOT_MODIFIED_DOC)
async def read_exercise(
    request: Request, user: CurrentUser, exercise_id: uuid.UUID, session: DbSession
) -> Response:
    """One exercise with steps, form cues, and its easier / harder / alternative moves."""
    try:
        detail = await exercise_service.get_exercise(session, user.id, exercise_id)
    except exercise_service.ExerciseNotFoundError as exc:
        raise NotFound("No exercise with this id") from exc
    return json_with_etag(request, detail)

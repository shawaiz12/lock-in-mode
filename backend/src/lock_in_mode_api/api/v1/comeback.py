"""Coming back after a break (ADR 0021): the opt-out. The easing itself shows up in the
plan (`comeback`, `comeback_week`) and in the workouts' numbers."""

from fastapi import APIRouter, status

from lock_in_mode_api.api.deps import CurrentUser, DbSession
from lock_in_mode_api.api.errors import NotFound
from lock_in_mode_api.services import comeback as comeback_service

router = APIRouter(tags=["comeback"])


@router.delete("/me/comeback", status_code=status.HTTP_204_NO_CONTENT)
async def end_comeback(user: CurrentUser, session: DbSession) -> None:
    """ "I kept training elsewhere": workouts not started yet go back to the user's normal
    numbers. A workout already started keeps the numbers it started with. Before the first
    workout back, this also keeps the block's recovery week."""
    try:
        await comeback_service.opt_out(session, user.id)
    except comeback_service.NoComebackError as exc:
        raise NotFound("No break to come back from") from exc

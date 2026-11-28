"""The waitlist (ADR 0037). No sign-in: the waitlist page calls these from the browser.

POST   /waitlist               join (or find your spot if you're on it already)
GET    /waitlist/count         what the page may say about the list
GET    /waitlist/{code}        a spot in line, by link code
POST   /waitlist/leave         leave for good, with the private key the page kept
POST   /waitlist/visits        "the page was opened", once per browser per day
"""

from fastapi import APIRouter, Depends, Response, status

from lock_in_mode_api.api.deps import DbSession
from lock_in_mode_api.api.errors import WaitlistEntryNotFound
from lock_in_mode_api.api.rate_limit import rate_limit, waitlist_join_limit
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.schemas.waitlist import (
    CountVisit,
    JoinedWaitlist,
    JoinWaitlist,
    LeaveWaitlist,
    WaitlistCount,
    WaitlistSpot,
)
from lock_in_mode_api.services import waitlist as service

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


def _spot(spot: service.Spot) -> WaitlistSpot:
    return WaitlistSpot(
        referral_code=spot.referral_code,
        position=spot.position,
        friends_joined=spot.friends_joined,
        on_list=spot.on_list,
        top_spots=settings.waitlist_top_spots,
        in_top=spot.in_top,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("waitlist")), Depends(waitlist_join_limit)],
    responses={200: {"model": JoinedWaitlist, "description": "Already on the list"}},
)
async def join_waitlist(
    body: JoinWaitlist, session: DbSession, response: Response
) -> JoinedWaitlist:
    """Join the waitlist. 201 with a one-time private `key` for a new signup; 200 with the
    spot and no key for an email that's already on the list (nothing about it changes).
    `ref` (a friend's link code) and `source` (?s= on the link) are optional; a code nobody
    has is ignored."""
    joined = await service.join(session, body.email, body.trains_at, body.ref, body.source)
    if joined.already_on_list:
        response.status_code = status.HTTP_200_OK
    return JoinedWaitlist(
        **_spot(joined.spot).model_dump(), already_on_list=joined.already_on_list, key=joined.key
    )


@router.get("/count")
async def waitlist_count(session: DbSession, response: Response) -> WaitlistCount:
    """The offer and the size of the list, for the page. `count` is null until the list
    reaches `waitlist_count_shown_from` people: real numbers only, never padded."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return WaitlistCount(
        count=service.shown_count(await service.on_list(session)),
        founding_discount_percent=settings.waitlist_founding_discount_percent,
        top_spots=settings.waitlist_top_spots,
    )


@router.post(
    "/visits",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("waitlist-visit"))],
)
async def count_visit(body: CountVisit, session: DbSession) -> None:
    """The page was opened (once per browser per day). Counts only: no IP, no cookie."""
    await service.count_visit(session, body.source)


@router.post(
    "/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("waitlist-leave"))],
)
async def leave_waitlist(body: LeaveWaitlist, session: DbSession) -> None:
    """Leave the waitlist for good: the email and everything with it is deleted. Needs the
    private key given at signup, so a shared link can't remove its owner."""
    try:
        await service.leave(session, body.key)
    except service.NotOnWaitlistError as exc:
        raise WaitlistEntryNotFound from exc


@router.get("/{code}", dependencies=[Depends(rate_limit("waitlist-spot"))])
async def waitlist_spot(code: str, session: DbSession) -> WaitlistSpot:
    """A spot in line by link code (any case). The page asks on every visit, so the spot is
    always current."""
    clean = service.clean_code(code)
    if clean is None:
        raise WaitlistEntryNotFound
    try:
        return _spot(await service.spot(session, clean))
    except service.NotOnWaitlistError as exc:
        raise WaitlistEntryNotFound from exc

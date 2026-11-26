from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.api.deps import AppleIdentity, CurrentUser, DbSession, GoogleIdentity
from lock_in_mode_api.api.errors import (
    ProfileNotFound,
    ProviderAccountInUse,
    ProviderAlreadyLinked,
)
from lock_in_mode_api.api.rate_limit import export_rate_limit
from lock_in_mode_api.models import User
from lock_in_mode_api.models.enums import LeavingReason
from lock_in_mode_api.schemas.profile import ProfileRead, ProfileWrite, SafetyScreen
from lock_in_mode_api.schemas.user import AccountDeletion, UserRead, UserUpdate
from lock_in_mode_api.schemas.week import WeekRead
from lock_in_mode_api.services import account as account_service
from lock_in_mode_api.services import auth as auth_service
from lock_in_mode_api.services import export as export_service
from lock_in_mode_api.services import profile as profile_service
from lock_in_mode_api.services import sign_in_offer
from lock_in_mode_api.services import week as week_service
from lock_in_mode_api.services.auth import Provider

router = APIRouter(prefix="/me", tags=["me"])

# Note on parameter order: FastAPI resolves dependencies in the order they're written.
# `user` comes first so an unauthenticated call gets 401 before any token verification.
# Every endpoint here works for guests: no sign-in is needed to onboard or train.


async def _user_read(session: AsyncSession, user: User) -> UserRead:
    """A guest also gets what they'd lose by losing this phone (ADR 0026)."""
    read = UserRead.model_validate(user)
    if not user.is_guest:
        return read
    summary = await sign_in_offer.summarize(session, user.id)
    return read.model_copy(update={"progress_summary": summary})


@router.get("")
async def read_me(user: CurrentUser, session: DbSession) -> UserRead:
    """Guests also get `progress_summary`: for a "Protect your progress" card (ADR 0026)."""
    return await _user_read(session, user)


@router.get("/week")
async def read_week(user: CurrentUser, session: DbSession) -> WeekRead:
    """This week's ring ("2 of 3") and the weekly streak with its freezes (ADR 0034)."""
    return await week_service.read_week(session, user.id)


@router.patch("")
async def update_me(user: CurrentUser, body: UserUpdate, session: DbSession) -> UserRead:
    """Change only what's sent: the optional name (null clears it), the "Share usage
    data" switch (false also erases past usage events), the phone's time zone and the
    training reminder (null turns it off). None of these change the plan."""
    user = await profile_service.update_user(session, user, body)
    return await _user_read(session, user)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": AccountDeletion,
            "description": "Google/Apple account: erased on `delete_after`",
        },
        status.HTTP_204_NO_CONTENT: {"description": "Guest: erased now"},
    },
)
async def delete_me(
    user: CurrentUser, session: DbSession, reason: LeavingReason | None = None
) -> Response:
    """Delete the account and everything in it (ADR 0024). Show "This can't be undone" first.

    - Guest → **204**: erased now.
    - Google/Apple account → **202** `{delete_after}`: signed out on every device now,
      erased after 30 days. Signing in with Google/Apple before then cancels it.

    `reason` is the optional "Why are you leaving?". It's kept with no link to the person,
    and only once the account is really gone.
    """
    if user.is_guest:
        await account_service.delete_guest(session, user, reason)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    delete_after = await account_service.schedule_deletion(session, user, reason)
    return JSONResponse(
        AccountDeletion(delete_after=delete_after).model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get(
    "/export",
    dependencies=[Depends(export_rate_limit)],
    responses={
        status.HTTP_200_OK: {
            "description": "`lock-in-mode-data.json`: everything stored about this account",
            "content": {"application/json": {}},
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "More than 3 in this hour"},
    },
)
async def export_my_data(user: CurrentUser, session: DbSession) -> Any:
    """ "Download my data" (ADR 0027): one JSON file with the account, profile, every plan
    and workout, every logged set, progress, swaps, comebacks and usage events. Guests too.

    Not in it: sign-in tokens and Google/Apple account ids (`signed_in_with` names the
    linked providers). 3 per account per hour; a 4th gets 429 `rate_limited`. An account
    waiting to be deleted is signed out, so offer this on the delete screen first.
    """
    data = await export_service.build_export(session, user.id)
    return JSONResponse(
        jsonable_encoder(data),
        headers={
            "Content-Disposition": 'attachment; filename="lock-in-mode-data.json"',
            "Cache-Control": "no-store",
        },
    )


# --- onboarding (ADR 0012) ----------------------------------------------------------


@router.get("/profile")
async def read_profile(user: CurrentUser, session: DbSession) -> ProfileRead:
    """404 `profile_not_found` means "show onboarding"."""
    try:
        profile = await profile_service.get_profile(session, user.id)
    except profile_service.ProfileNotFoundError as exc:
        raise ProfileNotFound("Finish onboarding first") from exc
    return ProfileRead.model_validate(profile)


@router.put(
    "/profile",
    responses={status.HTTP_201_CREATED: {"model": ProfileRead, "description": "Created"}},
)
async def save_profile(
    user: CurrentUser, body: ProfileWrite, session: DbSession, response: Response
) -> ProfileRead:
    """Save every onboarding answer. 201 the first time, 200 when replacing.

    The safety fields are never changed here; use `POST /me/safety-screen`.
    """
    profile, created = await profile_service.save_profile(session, user.id, body)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return ProfileRead.model_validate(profile)


@router.post("/safety-screen")
async def take_safety_screen(
    user: CurrentUser, body: SafetyScreen, session: DbSession
) -> ProfileRead:
    """Required before workout 1. Any "yes" → `needs_low_intensity`: the app shows
    "please check with a doctor first" and the plan stays gentle. Answers aren't stored.
    """
    try:
        profile = await profile_service.record_safety_screen(session, user.id, body)
    except profile_service.ProfileNotFoundError as exc:
        raise ProfileNotFound("Save the profile before the safety screen") from exc
    return ProfileRead.model_validate(profile)


# --- linking a guest to Google / Apple (ADR 0006) ------------------------------------


@router.post("/link/google")
async def link_google(user: CurrentUser, identity: GoogleIdentity, session: DbSession) -> UserRead:
    """Attach a Google account to the signed-in user. For a guest, this saves progress.

    409 means the Google account already belongs to someone else: the app should warn
    that this device's guest progress won't come along, then call `POST /auth/google`.
    """
    return await _link(session, user, Provider.GOOGLE, identity.sub, "Google")


@router.post("/link/apple")
async def link_apple(user: CurrentUser, identity: AppleIdentity, session: DbSession) -> UserRead:
    """Attach an Apple account to the signed-in user. Same rules as `/me/link/google`."""
    return await _link(session, user, Provider.APPLE, identity.sub, "Apple")


async def _link(
    session: AsyncSession, user: User, provider: Provider, sub: str, name: str
) -> UserRead:
    try:
        user = await auth_service.link_provider(session, user, provider, sub)
    except auth_service.ProviderAccountInUseError as exc:
        raise ProviderAccountInUse(f"This {name} account already belongs to another user") from exc
    except auth_service.ProviderAlreadyLinkedError as exc:
        raise ProviderAlreadyLinked(
            f"A different {name} account is already linked to this user"
        ) from exc
    return await _user_read(session, user)

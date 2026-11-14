from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.api.deps import AppleIdentity, CurrentUser, DbSession, GoogleIdentity
from lock_in_mode_api.models import User
from lock_in_mode_api.schemas.user import UserRead
from lock_in_mode_api.services import auth as auth_service
from lock_in_mode_api.services.auth import Provider

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/link/google")
async def link_google(identity: GoogleIdentity, user: CurrentUser, session: DbSession) -> UserRead:
    """Attach a Google account to the signed-in user. For a guest, this saves progress.

    409 means the Google account already belongs to someone else: the app should warn
    that this device's guest progress won't come along, then call `POST /auth/google`.
    """
    return await _link(session, user, Provider.GOOGLE, identity.sub, "Google")


@router.post("/link/apple")
async def link_apple(identity: AppleIdentity, user: CurrentUser, session: DbSession) -> UserRead:
    """Attach an Apple account to the signed-in user. Same rules as `/me/link/google`."""
    return await _link(session, user, Provider.APPLE, identity.sub, "Apple")


async def _link(
    session: AsyncSession, user: User, provider: Provider, sub: str, name: str
) -> UserRead:
    try:
        user = await auth_service.link_provider(session, user, provider, sub)
    except auth_service.ProviderAccountInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This {name} account already belongs to another user",
        ) from exc
    except auth_service.ProviderAlreadyLinkedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A different {name} account is already linked to this user",
        ) from exc
    return UserRead.model_validate(user)

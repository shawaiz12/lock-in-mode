from fastapi import APIRouter, HTTPException, status

from lock_in_mode_api.api.deps import AppleIdentity, DbSession, GoogleIdentity
from lock_in_mode_api.schemas.auth import RefreshRequest, TokenPair
from lock_in_mode_api.services import auth as auth_service
from lock_in_mode_api.services.auth import Provider

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/guest", status_code=status.HTTP_201_CREATED)
async def sign_in_as_guest(session: DbSession) -> TokenPair:
    """Start without an account. The refresh token is this guest's only way back in."""
    return await auth_service.sign_in_as_guest(session)


@router.post("/google")
async def sign_in_with_google(identity: GoogleIdentity, session: DbSession) -> TokenPair:
    """Sign in, or create an account, with a Google ID token.

    Guests who want to keep their progress call `POST /me/link/google` first (ADR 0006).
    """
    return await auth_service.sign_in_with_provider(session, Provider.GOOGLE, identity.sub)


@router.post("/apple")
async def sign_in_with_apple(identity: AppleIdentity, session: DbSession) -> TokenPair:
    """Sign in, or create an account, with an Apple ID token and its raw nonce."""
    return await auth_service.sign_in_with_provider(session, Provider.APPLE, identity.sub)


@router.post("/refresh")
async def refresh(body: RefreshRequest, session: DbSession) -> TokenPair:
    try:
        return await auth_service.rotate_refresh_token(session, body.refresh_token)
    except auth_service.InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, session: DbSession) -> None:
    """Always 204, even for unknown tokens, so this can't be used to probe tokens."""
    await auth_service.sign_out(session, body.refresh_token)

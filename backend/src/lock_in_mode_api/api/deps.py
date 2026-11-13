"""Shared FastAPI dependencies: database session and the signed-in user."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.db import get_db_session
from lock_in_mode_api.core.security import InvalidAccessTokenError, decode_access_token
from lock_in_mode_api.models import User

# Request-scoped database session.
type DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# auto_error=False so we can return our own 401 (FastAPI's default is 403).
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidAccessTokenError as exc:
        raise _unauthorized("Invalid or expired access token") from exc

    user = await session.get(User, user_id)
    if user is None:  # valid token, but the account has since been deleted
        raise _unauthorized("Invalid or expired access token")
    return user


# Any endpoint that takes `user: CurrentUser` requires a valid access token.
type CurrentUser = Annotated[User, Depends(get_current_user)]

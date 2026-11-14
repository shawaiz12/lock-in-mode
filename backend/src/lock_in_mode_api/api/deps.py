"""Shared FastAPI dependencies: database session, signed-in user, verified ID tokens."""

import asyncio
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.api.errors import (
    InvalidAccessToken,
    InvalidIdToken,
    NotAuthenticated,
    ProviderUnavailable,
)
from lock_in_mode_api.core.db import get_db_session
from lock_in_mode_api.core.identity import (
    IdTokenVerifier,
    InvalidIdTokenError,
    ProviderNotConfiguredError,
    VerifiedIdentity,
    get_apple_verifier,
    get_google_verifier,
)
from lock_in_mode_api.core.security import InvalidAccessTokenError, decode_access_token
from lock_in_mode_api.models import User
from lock_in_mode_api.schemas.auth import AppleIdTokenRequest, IdTokenRequest

# Request-scoped database session.
type DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# auto_error=False so we can return our own 401 (FastAPI's default is 403).
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise NotAuthenticated
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidAccessTokenError as exc:
        raise InvalidAccessToken from exc

    user = await session.get(User, user_id)
    if user is None:  # valid token, but the account has since been deleted
        raise InvalidAccessToken
    return user


# Any endpoint that takes `user: CurrentUser` requires a valid access token.
type CurrentUser = Annotated[User, Depends(get_current_user)]


# --- Google / Apple ID tokens (ADR 0005) ----------------------------------------------
# Routes ask for `identity: GoogleIdentity` and receive an already-verified account.
# Tests replace `google_verifier` / `apple_verifier` with one that trusts a local key.


def _provider_unavailable(name: str) -> ProviderUnavailable:
    return ProviderUnavailable(f"Sign in with {name} is not available")


def google_verifier() -> IdTokenVerifier:
    try:
        return get_google_verifier()
    except ProviderNotConfiguredError as exc:
        raise _provider_unavailable("Google") from exc


def apple_verifier() -> IdTokenVerifier:
    try:
        return get_apple_verifier()
    except ProviderNotConfiguredError as exc:
        raise _provider_unavailable("Apple") from exc


async def _verify(
    verifier: IdTokenVerifier, id_token: str, raw_nonce: str | None = None
) -> VerifiedIdentity:
    try:
        # verify() may download the provider's public keys (blocking network I/O),
        # so run it in a worker thread instead of freezing the event loop.
        return await asyncio.to_thread(verifier.verify, id_token, raw_nonce=raw_nonce)
    except InvalidIdTokenError as exc:
        raise InvalidIdToken from exc


async def google_identity(
    body: IdTokenRequest,
    verifier: Annotated[IdTokenVerifier, Depends(google_verifier)],
) -> VerifiedIdentity:
    return await _verify(verifier, body.id_token)


async def apple_identity(
    body: AppleIdTokenRequest,
    verifier: Annotated[IdTokenVerifier, Depends(apple_verifier)],
) -> VerifiedIdentity:
    return await _verify(verifier, body.id_token, raw_nonce=body.nonce)


type GoogleIdentity = Annotated[VerifiedIdentity, Depends(google_identity)]
type AppleIdentity = Annotated[VerifiedIdentity, Depends(apple_identity)]

"""Sign-in and token lifecycle (ADR 0005).

Functions here own the transaction: they commit on success. Routes stay thin.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from lock_in_mode_api.models import RefreshToken, User
from lock_in_mode_api.schemas.auth import TokenPair


class InvalidRefreshTokenError(Exception):
    """Unknown, expired, revoked or reused refresh token. Callers answer 401."""


def _now() -> datetime:
    return datetime.now(UTC)


async def _issue_token_pair(
    session: AsyncSession, user_id: uuid.UUID, *, family_id: uuid.UUID, now: datetime
) -> TokenPair:
    """Store a new refresh token (hashed) and return it with a fresh access token."""
    raw_refresh_token = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return TokenPair(
        access_token=create_access_token(user_id, now=now),
        refresh_token=raw_refresh_token,  # the only time the raw token ever exists
        expires_in=settings.access_token_ttl_minutes * 60,
    )


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def sign_in_as_guest(session: AsyncSession) -> TokenPair:
    now = _now()
    user = User(is_guest=True)
    session.add(user)
    await session.flush()  # assigns user.id

    tokens = await _issue_token_pair(session, user.id, family_id=uuid.uuid4(), now=now)
    await session.commit()
    return tokens


async def rotate_refresh_token(session: AsyncSession, raw_refresh_token: str) -> TokenPair:
    """Swap a refresh token for a new pair. Reusing an old token revokes its family."""
    now = _now()
    token = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_refresh_token))
        # Lock the row: two simultaneous refreshes with the same token can't both win.
        .with_for_update()
    )
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise InvalidRefreshTokenError

    if token.used_at is not None:
        # This token was already exchanged once, so someone holds a copy.
        await _revoke_family(session, token.family_id, now)
        # Commit BEFORE raising: the caller's error handling must not roll this back.
        await session.commit()
        raise InvalidRefreshTokenError

    token.used_at = now
    tokens = await _issue_token_pair(session, token.user_id, family_id=token.family_id, now=now)
    await session.commit()
    return tokens


async def sign_out(session: AsyncSession, raw_refresh_token: str) -> None:
    """Revoke this device's whole token family. Unknown tokens are ignored."""
    family_id = await session.scalar(
        select(RefreshToken.family_id).where(
            RefreshToken.token_hash == hash_refresh_token(raw_refresh_token)
        )
    )
    if family_id is not None:
        await _revoke_family(session, family_id, _now())
        await session.commit()

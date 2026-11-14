"""Sign-in, account linking and token lifecycle (ADR 0005, ADR 0006).

Functions here own the transaction: they commit on success. Routes stay thin.
"""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

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


class ProviderAccountInUseError(Exception):
    """This Google/Apple account already belongs to another user. Callers answer 409."""


class ProviderAlreadyLinkedError(Exception):
    """This user already has a different Google/Apple account linked. Callers answer 409."""


class Provider(StrEnum):
    GOOGLE = "google"
    APPLE = "apple"


def _sub_column(provider: Provider) -> InstrumentedAttribute[str | None]:
    """The users column that stores this provider's account id."""
    return User.google_sub if provider is Provider.GOOGLE else User.apple_sub


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


async def sign_in_with_provider(session: AsyncSession, provider: Provider, sub: str) -> TokenPair:
    """Sign in with a verified Google/Apple account, creating the user the first time.

    Always signs into the account that owns `sub`. A guest who wants to keep their
    progress calls `link_provider` first (ADR 0006).
    """
    column = _sub_column(provider)
    # "Create it unless it exists" in ONE statement. Two first sign-ins at the same
    # moment can't create two users: the second insert hits UNIQUE(sub), does
    # nothing, and returns no row.
    user_id: uuid.UUID | None = await session.scalar(
        insert(User)
        .values({column.key: sub, "is_guest": False})
        .on_conflict_do_nothing(index_elements=[column])
        .returning(User.id)
    )
    if user_id is None:  # the account already existed
        user_id = (await session.execute(select(User.id).where(column == sub))).scalar_one()

    tokens = await _issue_token_pair(session, user_id, family_id=uuid.uuid4(), now=_now())
    await session.commit()
    return tokens


async def link_provider(session: AsyncSession, user: User, provider: Provider, sub: str) -> User:
    """Attach a verified Google/Apple account to `user` (ADR 0006).

    For a guest this saves their progress: same user id, so their tokens keep working.
    """
    column = _sub_column(provider)
    current_sub: str | None = getattr(user, column.key)
    if current_sub == sub:
        return user  # already linked: a retried request succeeds again
    if current_sub is not None:
        raise ProviderAlreadyLinkedError

    setattr(user, column.key, sub)
    user.is_guest = False
    try:
        await session.commit()
    except IntegrityError as exc:
        # No "is it taken?" query first: two requests could both pass that check.
        # The UNIQUE constraint on the sub column is the only reliable referee, and
        # it is the only constraint this UPDATE can break.
        await session.rollback()
        raise ProviderAccountInUseError from exc
    return user

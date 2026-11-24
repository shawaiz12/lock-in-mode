"""Guest sign-in life and lost guests (ADR 0027): a guest's refresh token lasts a year from
its last use; Google/Apple accounts keep 60 days; the hourly cleanup erases guests with no
usable token left, after a day's margin, and never touches anyone who can still get in.

Inside a test the database clock is frozen, so time passes by moving rows back.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.models import RefreshToken, User
from lock_in_mode_api.schemas.auth import TokenPair
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.services import account
from tests.api.test_account_deletion import (
    _auth,
    _full_user,
    _google,
    _guest,
    _rows_left,
    _user_tables,
)

type MakeIdToken = Callable[..., str]


@pytest.fixture
async def library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


ME = "/api/v1/me"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


async def _newest_token(db: AsyncSession) -> RefreshToken:
    """The one token that still works (unused, not revoked). The frozen test clock gives
    every token the same `created_at`, so "newest" can't be read from that."""
    [token] = (
        await db.scalars(
            select(RefreshToken)
            .where(RefreshToken.used_at.is_(None), RefreshToken.revoked_at.is_(None))
            .execution_options(populate_existing=True)
        )
    ).all()
    return token


def _days_left(token: RefreshToken) -> float:
    return (token.expires_at - datetime.now(UTC)) / timedelta(days=1)


async def _refresh(client: AsyncClient, tokens: TokenPair) -> TokenPair:
    response = await client.post(REFRESH, json={"refresh_token": tokens.refresh_token})
    assert response.status_code == 200, response.text
    return TokenPair.model_validate(response.json())


def _seconds(n: float) -> Any:
    """An interval of `n` seconds (make_interval's last argument takes fractions)."""
    return func.make_interval(0, 0, 0, 0, 0, 0, n)


async def _age_users(db: AsyncSession, days: float) -> None:
    """Every user was made `days` ago (the lost-guest rule leaves day-old guests alone)."""
    await db.execute(update(User).values(created_at=func.now() - _seconds(days * 86400)))
    await db.flush()


async def _expire_tokens(db: AsyncSession, hours_ago: float) -> None:
    """Every refresh token ran out `hours_ago` hours ago (by the database clock)."""
    await db.execute(
        update(RefreshToken).values(expires_at=func.now() - _seconds(hours_ago * 3600))
    )
    await db.flush()


async def _user_count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User)) or 0


# --- how long a sign-in lasts -------------------------------------------------------------


async def test_a_guest_token_lasts_a_year_and_each_refresh_renews_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    assert settings.guest_refresh_token_ttl_days == 365
    tokens = await _guest(client)
    assert 364.9 < _days_left(await _newest_token(db_session)) <= 365

    await _refresh(client, tokens)

    assert 364.9 < _days_left(await _newest_token(db_session)) <= 365


async def test_google_and_apple_accounts_keep_60_days(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    tokens = await _google(client, google_id_token("g"))
    assert 59.9 < _days_left(await _newest_token(db_session)) <= 60

    await _refresh(client, tokens)

    assert 59.9 < _days_left(await _newest_token(db_session)) <= 60


async def test_a_guest_who_links_gets_60_days_from_the_next_refresh(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    tokens = await _guest(client)
    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("g")}, headers=_auth(tokens)
    )
    assert link.status_code == 200

    await _refresh(client, tokens)

    assert 59.9 < _days_left(await _newest_token(db_session)) <= 60


# --- lost guests --------------------------------------------------------------------------


async def test_a_signed_out_guest_is_erased_with_everything(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    tokens = await _guest(client)
    await _full_user(client, db_session, tokens)
    other = await _guest(client)  # still signed in: stays
    await client.post(LOGOUT, json={"refresh_token": tokens.refresh_token})
    await _age_users(db_session, 2)

    assert await account.purge_lost_guests(db_session) == 1

    # Only the other guest is left: their user row, their token, their sign-up event.
    assert await _rows_left(db_session) == {
        t.name: (1 if t.name in {"users", "refresh_tokens", "events"} else 0)
        for t in _user_tables()
    }
    assert (await client.get(ME, headers=_auth(tokens))).status_code == 401
    assert (await client.get(ME, headers=_auth(other))).status_code == 200


async def test_a_guest_made_less_than_a_day_ago_is_left_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _guest(client)
    await client.post(LOGOUT, json={"refresh_token": tokens.refresh_token})
    await _age_users(db_session, 0.9)

    assert await account.purge_lost_guests(db_session) == 0

    await _age_users(db_session, 1.1)
    assert await account.purge_lost_guests(db_session) == 1


@pytest.mark.parametrize(
    ("hours_ago", "erased"), [(-1, 0), (12, 0), (23, 0), (25, 1), (24 * 400, 1)]
)
async def test_an_expired_token_counts_after_a_days_margin(
    client: AsyncClient, db_session: AsyncSession, hours_ago: float, erased: int
) -> None:
    await _guest(client)
    await _age_users(db_session, 500)
    await _expire_tokens(db_session, hours_ago)

    assert await account.purge_lost_guests(db_session) == erased
    assert await _user_count(db_session) == 1 - erased


async def test_a_refreshed_guest_still_gets_in_through_the_newest_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _guest(client)
    tokens = await _refresh(client, tokens)
    tokens = await _refresh(client, tokens)  # two used tokens, one live
    await _age_users(db_session, 30)

    assert await account.purge_lost_guests(db_session) == 0
    assert (await client.get(ME, headers=_auth(tokens))).status_code == 200


async def test_a_guest_locked_out_after_a_reused_token_is_erased(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _guest(client)
    await _refresh(client, first)
    reused = await client.post(REFRESH, json={"refresh_token": first.refresh_token})
    assert reused.status_code == 401  # the whole family is revoked
    await _age_users(db_session, 2)

    assert await account.purge_lost_guests(db_session) == 1


async def test_google_and_apple_accounts_are_never_lost_guests(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    google = await _google(client, google_id_token("g"))
    linked = await _guest(client)
    await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("l")}, headers=_auth(linked)
    )
    for tokens in (google, linked):
        await client.post(LOGOUT, json={"refresh_token": tokens.refresh_token})
    await _age_users(db_session, 500)
    await _expire_tokens(db_session, 24 * 400)

    assert await account.purge_lost_guests(db_session) == 0
    assert await _user_count(db_session) == 2


async def test_lost_guests_are_erased_in_batches(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for _ in range(5):
        tokens = await _guest(client)
        await client.post(LOGOUT, json={"refresh_token": tokens.refresh_token})
    kept = await _guest(client)
    await _age_users(db_session, 3)

    assert await account.purge_lost_guests(db_session, batch=2) == 5  # 2 + 2 + 1

    assert await _user_count(db_session) == 1
    assert (await client.get(ME, headers=_auth(kept))).status_code == 200
    assert await account.purge_lost_guests(db_session) == 0


async def test_a_used_token_is_no_way_back_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Presenting a used token revokes its family (ADR 0005), so a guest whose only
    unrevoked, unexpired token was already used is lost too."""
    tokens = await _guest(client)
    await db_session.execute(update(RefreshToken).values(used_at=func.now()))
    await _age_users(db_session, 2)

    assert await account.purge_lost_guests(db_session) == 1
    refreshed = await client.post(REFRESH, json={"refresh_token": tokens.refresh_token})
    assert refreshed.status_code == 401

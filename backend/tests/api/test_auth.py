"""End-to-end tests for guest sign-in, refresh rotation, logout and /me (ADR 0005)."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from lock_in_mode_api.models import RefreshToken, User
from lock_in_mode_api.schemas.auth import TokenPair


async def _sign_in_as_guest(client: AsyncClient) -> TokenPair:
    response = await client.post("/api/v1/auth/guest")
    assert response.status_code == 201
    return TokenPair.model_validate(response.json())  # also checks the response shape


async def _refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})


async def _me(client: AsyncClient, access_token: str) -> Response:
    return await client.get("/api/v1/me", headers={"Authorization": f"Bearer {access_token}"})


# --- guest sign-in and /me --------------------------------------------------------


async def test_guest_sign_in_returns_a_working_token_pair(client: AsyncClient) -> None:
    tokens = await _sign_in_as_guest(client)

    assert tokens.token_type == "bearer"
    assert tokens.expires_in == 15 * 60
    me = await _me(client, tokens.access_token)
    assert me.status_code == 200
    assert me.json()["is_guest"] is True


async def test_refresh_token_is_stored_only_as_a_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _sign_in_as_guest(client)

    stored_hashes = (await db_session.scalars(select(RefreshToken.token_hash))).all()

    assert stored_hashes == [hash_refresh_token(tokens.refresh_token)]
    assert tokens.refresh_token not in stored_hashes


async def test_me_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_a_garbage_token_is_401(client: AsyncClient) -> None:
    assert (await _me(client, "not-a-jwt")).status_code == 401


async def test_me_with_an_expired_token_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = User(is_guest=True)
    db_session.add(user)
    await db_session.flush()
    expired = create_access_token(user.id, now=datetime.now(UTC) - timedelta(hours=1))

    assert (await _me(client, expired)).status_code == 401


async def test_me_for_a_deleted_account_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _sign_in_as_guest(client)
    await db_session.execute(delete(User))

    assert (await _me(client, tokens.access_token)).status_code == 401


async def test_me_with_a_token_for_an_unknown_user_is_401(client: AsyncClient) -> None:
    assert (await _me(client, create_access_token(uuid.uuid4()))).status_code == 401


# --- refresh rotation ---------------------------------------------------------------


async def test_refresh_returns_a_new_pair_that_works(client: AsyncClient) -> None:
    first = await _sign_in_as_guest(client)

    response = await _refresh(client, first.refresh_token)

    assert response.status_code == 200
    second = TokenPair.model_validate(response.json())
    assert second.refresh_token != first.refresh_token
    assert (await _me(client, second.access_token)).status_code == 200


async def test_reusing_a_refresh_token_revokes_the_whole_family(client: AsyncClient) -> None:
    """The stolen-token scenario: an old token comes back after it was rotated."""
    first = await _sign_in_as_guest(client)
    second = TokenPair.model_validate((await _refresh(client, first.refresh_token)).json())

    reuse = await _refresh(client, first.refresh_token)  # attacker replays the old one

    assert reuse.status_code == 401
    # The newest token is revoked too, so the attacker's copy is useless as well.
    assert (await _refresh(client, second.refresh_token)).status_code == 401


async def test_unknown_refresh_token_is_401(client: AsyncClient) -> None:
    assert (await _refresh(client, "made-up-token")).status_code == 401


async def test_expired_refresh_token_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    tokens = await _sign_in_as_guest(client)
    await db_session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    assert (await _refresh(client, tokens.refresh_token)).status_code == 401


async def test_empty_refresh_token_is_rejected_by_validation(client: AsyncClient) -> None:
    assert (await _refresh(client, "")).status_code == 422


# --- logout ---------------------------------------------------------------------------


async def test_logout_revokes_the_refresh_token(client: AsyncClient) -> None:
    tokens = await _sign_in_as_guest(client)

    response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens.refresh_token}
    )

    assert response.status_code == 204
    assert (await _refresh(client, tokens.refresh_token)).status_code == 401


async def test_logout_with_an_unknown_token_still_returns_204(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": "made-up-token"})

    assert response.status_code == 204


async def test_logout_on_one_device_keeps_other_devices_signed_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    phone = await _sign_in_as_guest(client)
    # Simulate a second device for the same user: a separate token family.
    user_id = await db_session.scalar(select(RefreshToken.user_id))
    assert user_id is not None
    tablet_token = generate_refresh_token()
    db_session.add(
        RefreshToken(
            user_id=user_id,
            family_id=uuid.uuid4(),
            token_hash=hash_refresh_token(tablet_token),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.flush()

    await client.post("/api/v1/auth/logout", json={"refresh_token": phone.refresh_token})

    assert (await _refresh(client, phone.refresh_token)).status_code == 401
    assert (await _refresh(client, tablet_token)).status_code == 200

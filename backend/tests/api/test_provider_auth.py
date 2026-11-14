"""Google/Apple sign-in and account linking, end to end (ADR 0005, ADR 0006).

`google_id_token` / `apple_id_token` (tests/api/conftest.py) stand in for Google and
Apple: they sign real ID tokens with a local key the API has been told to trust.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core import identity
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.models import User
from lock_in_mode_api.schemas.auth import TokenPair

type MakeIdToken = Callable[..., str]

APPLE_NONCE = "raw-nonce-from-the-app"  # must match tests/api/conftest.py


def _auth(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _guest(client: AsyncClient) -> TokenPair:
    response = await client.post("/api/v1/auth/guest")
    assert response.status_code == 201
    return TokenPair.model_validate(response.json())


async def _sign_in_google(client: AsyncClient, id_token: str) -> Response:
    return await client.post("/api/v1/auth/google", json={"id_token": id_token})


async def _me(client: AsyncClient, access_token: str) -> dict[str, Any]:
    response = await client.get("/api/v1/me", headers=_auth(access_token))
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def _user_count(db_session: AsyncSession) -> int:
    return await db_session.scalar(select(func.count()).select_from(User)) or 0


# --- POST /auth/google and /auth/apple -------------------------------------------------


async def test_first_google_sign_in_creates_a_saved_account(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    response = await _sign_in_google(client, google_id_token("google-user-1"))

    assert response.status_code == 200
    me = await _me(client, TokenPair.model_validate(response.json()).access_token)
    assert me["is_guest"] is False
    assert "google_sub" not in me  # provider ids are never exposed
    user = await db_session.scalar(select(User).where(User.google_sub == "google-user-1"))
    assert user is not None
    assert str(user.id) == me["id"]


async def test_signing_in_again_returns_the_same_account(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    first = await _sign_in_google(client, google_id_token("google-user-1"))
    second = await _sign_in_google(client, google_id_token("google-user-1"))

    first_me = await _me(client, first.json()["access_token"])
    second_me = await _me(client, second.json()["access_token"])
    assert first_me["id"] == second_me["id"]
    assert await _user_count(db_session) == 1


async def test_apple_sign_in_with_the_right_nonce_works(
    client: AsyncClient, apple_id_token: MakeIdToken
) -> None:
    response = await client.post(
        "/api/v1/auth/apple", json={"id_token": apple_id_token(), "nonce": APPLE_NONCE}
    )

    assert response.status_code == 200
    assert (await _me(client, response.json()["access_token"]))["is_guest"] is False


async def test_apple_sign_in_with_the_wrong_nonce_is_401(
    client: AsyncClient, apple_id_token: MakeIdToken
) -> None:
    response = await client.post(
        "/api/v1/auth/apple", json={"id_token": apple_id_token(), "nonce": "replayed"}
    )

    assert response.status_code == 401


async def test_apple_sign_in_without_a_nonce_is_422(
    client: AsyncClient, apple_id_token: MakeIdToken
) -> None:
    response = await client.post("/api/v1/auth/apple", json={"id_token": apple_id_token()})

    assert response.status_code == 422


async def test_invalid_id_token_is_401(client: AsyncClient, google_id_token: MakeIdToken) -> None:
    response = await _sign_in_google(client, "not-a-real-token")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_empty_id_token_is_422(client: AsyncClient, google_id_token: MakeIdToken) -> None:
    response = await _sign_in_google(client, "")

    assert response.status_code == 422


async def test_unconfigured_provider_is_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No fake verifier here: the real one runs and finds no client ids configured.
    monkeypatch.setattr(settings, "google_client_ids", [])
    identity.get_google_verifier.cache_clear()

    response = await _sign_in_google(client, "any-token")

    assert response.status_code == 503


# --- POST /me/link/google and /me/link/apple ------------------------------------------


async def test_guest_links_a_new_google_account_and_keeps_everything(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    guest = await _guest(client)
    guest_id = (await _me(client, guest.access_token))["id"]

    response = await client.post(
        "/api/v1/me/link/google",
        json={"id_token": google_id_token("google-user-1")},
        headers=_auth(guest.access_token),
    )

    assert response.status_code == 200
    assert response.json()["id"] == guest_id  # the same user, not a new one
    assert response.json()["is_guest"] is False
    # Same user, so the guest's existing token keeps working...
    assert (await _me(client, guest.access_token))["id"] == guest_id
    # ...and signing in with Google on a new phone lands in this same account.
    on_new_phone = await _sign_in_google(client, google_id_token("google-user-1"))
    assert (await _me(client, on_new_phone.json()["access_token"]))["id"] == guest_id


async def test_linking_an_account_that_belongs_to_someone_else_is_409(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    await _sign_in_google(client, google_id_token("google-user-1"))  # someone else
    guest = await _guest(client)

    response = await client.post(
        "/api/v1/me/link/google",
        json={"id_token": google_id_token("google-user-1")},
        headers=_auth(guest.access_token),
    )

    assert response.status_code == 409
    me = await _me(client, guest.access_token)  # the guest is untouched
    assert me["is_guest"] is True
    guest_row = await db_session.get(User, me["id"])
    assert guest_row is not None
    assert guest_row.google_sub is None


async def test_warn_first_flow_after_a_409(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    """The whole ADR 0006 story: link → 409 → app warns → user confirms → sign in."""
    existing = await _sign_in_google(client, google_id_token("google-user-1"))
    existing_id = (await _me(client, existing.json()["access_token"]))["id"]
    guest = await _guest(client)

    link = await client.post(
        "/api/v1/me/link/google",
        json={"id_token": google_id_token("google-user-1")},
        headers=_auth(guest.access_token),
    )
    assert link.status_code == 409
    # (the app shows its warning here; the user taps "Continue")
    signed_in = await _sign_in_google(client, google_id_token("google-user-1"))

    assert (await _me(client, signed_in.json()["access_token"]))["id"] == existing_id


async def test_linking_the_same_account_twice_is_fine(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    guest = await _guest(client)
    body = {"id_token": google_id_token("google-user-1")}

    first = await client.post(
        "/api/v1/me/link/google", json=body, headers=_auth(guest.access_token)
    )
    retry = await client.post(
        "/api/v1/me/link/google", json=body, headers=_auth(guest.access_token)
    )

    assert (first.status_code, retry.status_code) == (200, 200)


async def test_replacing_a_linked_account_with_another_is_409(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    signed_in = await _sign_in_google(client, google_id_token("google-user-1"))

    response = await client.post(
        "/api/v1/me/link/google",
        json={"id_token": google_id_token("google-user-2")},
        headers=_auth(signed_in.json()["access_token"]),
    )

    assert response.status_code == 409


async def test_google_user_can_add_apple(
    client: AsyncClient,
    db_session: AsyncSession,
    google_id_token: MakeIdToken,
    apple_id_token: MakeIdToken,
) -> None:
    signed_in = await _sign_in_google(client, google_id_token("google-user-1"))

    response = await client.post(
        "/api/v1/me/link/apple",
        json={"id_token": apple_id_token("apple-user-1"), "nonce": APPLE_NONCE},
        headers=_auth(signed_in.json()["access_token"]),
    )

    assert response.status_code == 200
    user = await db_session.scalar(select(User).where(User.apple_sub == "apple-user-1"))
    assert user is not None
    assert user.google_sub == "google-user-1"


async def test_linking_requires_being_signed_in(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    response = await client.post(
        "/api/v1/me/link/google", json={"id_token": google_id_token("google-user-1")}
    )

    assert response.status_code == 401


async def test_linking_with_an_invalid_id_token_is_401(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    guest = await _guest(client)

    response = await client.post(
        "/api/v1/me/link/google",
        json={"id_token": "forged"},
        headers=_auth(guest.access_token),
    )

    assert response.status_code == 401
    assert (await _me(client, guest.access_token))["is_guest"] is True

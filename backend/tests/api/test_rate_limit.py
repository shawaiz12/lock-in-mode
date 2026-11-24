"""Per-IP rate limiting on sign-in endpoints (ADR 0008).

The limit is lowered to 2 per minute, and the limiter's clock is pinned, so tests
never depend on real time (no sleeping, no flaky failures at a minute boundary).
"""

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from lock_in_mode_api.api import rate_limit
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.redis import get_redis, redis_client
from lock_in_mode_api.main import app

type MakeIdToken = Callable[..., str]

MINUTE_START = 29_000_000 * 60.0  # some exact minute boundary


@pytest.fixture(autouse=True)
def _limit_two_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 2)
    _set_clock(monkeypatch, MINUTE_START + 45)  # 45 s into the minute


def _set_clock(monkeypatch: pytest.MonkeyPatch, now: float) -> None:
    monkeypatch.setattr(rate_limit, "clock", lambda: now)


@pytest.fixture
async def other_ip_client(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Same app and test DB as `client`, but requests come from another IP address."""
    transport = ASGITransport(app=app, client=("203.0.113.9", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as other:
        yield other


async def test_allows_the_limit_then_answers_429(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/guest")).status_code == 201
    assert (await client.post("/api/v1/auth/guest")).status_code == 201

    response = await client.post("/api/v1/auth/guest")

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "rate_limited"
    assert response.headers["Retry-After"] == "15"  # 45 s in, so 15 s to the next minute


async def test_a_new_minute_starts_a_fresh_count(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(3):
        await client.post("/api/v1/auth/guest")

    _set_clock(monkeypatch, MINUTE_START + 60)  # next minute

    assert (await client.post("/api/v1/auth/guest")).status_code == 201


async def test_each_ip_has_its_own_count(client: AsyncClient, other_ip_client: AsyncClient) -> None:
    for _ in range(3):
        await client.post("/api/v1/auth/guest")

    assert (await other_ip_client.post("/api/v1/auth/guest")).status_code == 201


async def test_each_endpoint_has_its_own_count(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    for _ in range(3):
        await client.post("/api/v1/auth/guest")

    response = await client.post("/api/v1/auth/google", json={"id_token": google_id_token()})

    assert response.status_code == 200


async def test_failed_attempts_count_too(client: AsyncClient, google_id_token: MakeIdToken) -> None:
    # Someone trying stolen or forged tokens is exactly who we want to slow down.
    bad = {"id_token": "forged"}
    assert (await client.post("/api/v1/auth/google", json=bad)).status_code == 401
    assert (await client.post("/api/v1/auth/google", json=bad)).status_code == 401

    response = await client.post("/api/v1/auth/google", json={"id_token": google_id_token()})

    assert response.status_code == 429


async def test_counters_expire_so_nothing_piles_up(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/guest")

    keys = await redis_client.keys("rl:guest:*")
    assert len(keys) == 1
    assert 0 < await redis_client.ttl(keys[0]) <= 60


async def test_refresh_is_not_rate_limited(client: AsyncClient) -> None:
    # Refresh tokens are 256 random bits: guessing one is hopeless, so no limit yet.
    for _ in range(3):
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
        assert response.status_code == 401


async def test_redis_down_lets_requests_through(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing listens on port 1, so every Redis command fails to connect.
    unreachable = Redis.from_url("redis://localhost:1/0", socket_connect_timeout=0.2)
    app.dependency_overrides[get_redis] = lambda: unreachable

    for _ in range(3):  # over the limit, but nothing can count it
        assert (await client.post("/api/v1/auth/guest")).status_code == 201

    assert "Rate limiting skipped: Redis unavailable" in caplog.text
    await unreachable.aclose()


# --- Behind the hosting proxy (ADR 0028) ------------------------------------------------
# The test client's own address plays the proxy. X-Forwarded-For carries what the proxy
# saw: its LAST entry is the real caller, anything before it was typed by the caller.


def _from(*forwarded_for: str) -> dict[str, str]:
    return {"X-Forwarded-For": ", ".join(forwarded_for)}


async def test_behind_a_proxy_the_forwarded_caller_is_counted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    alice, bob = _from("198.51.100.1"), _from("198.51.100.2")

    for _ in range(2):
        assert (await client.post("/api/v1/auth/guest", headers=alice)).status_code == 201

    # Same connection (the proxy), different real caller: a separate count.
    assert (await client.post("/api/v1/auth/guest", headers=alice)).status_code == 429
    assert (await client.post("/api/v1/auth/guest", headers=bob)).status_code == 201


async def test_made_up_addresses_in_front_do_not_dodge_the_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)

    statuses = [
        (
            await client.post("/api/v1/auth/guest", headers=_from(f"10.0.0.{n}", "198.51.100.1"))
        ).status_code
        for n in range(3)
    ]

    assert statuses == [201, 201, 429]


async def test_without_a_proxy_the_header_is_ignored(client: AsyncClient) -> None:
    # Local setting (0 hops): anyone can send the header, so it must change nothing.
    statuses = [
        (await client.post("/api/v1/auth/guest", headers=_from(f"198.51.100.{n}"))).status_code
        for n in range(3)
    ]

    assert statuses == [201, 201, 429]


def _request(headers: list[tuple[str, str]], peer: str = "192.0.2.50") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
            "client": (peer, 1234),
        }
    )


@pytest.mark.parametrize(
    ("hops", "headers", "expected"),
    [
        (0, [("X-Forwarded-For", "198.51.100.1")], "192.0.2.50"),
        (1, [("X-Forwarded-For", "198.51.100.1")], "198.51.100.1"),
        (1, [("X-Forwarded-For", " 6.6.6.6 ,198.51.100.1 ")], "198.51.100.1"),
        # Two proxies (e.g. a CDN in front of the platform): the second to last.
        (2, [("X-Forwarded-For", "6.6.6.6, 198.51.100.1, 203.0.113.80")], "198.51.100.1"),
        # Several headers are one list, in order.
        (1, [("X-Forwarded-For", "6.6.6.6"), ("X-Forwarded-For", "198.51.100.1")], "198.51.100.1"),
        # Missing or too short: not what our proxy sends, so use the connection.
        (1, [], "192.0.2.50"),
        (1, [("X-Forwarded-For", " , ")], "192.0.2.50"),
        (2, [("X-Forwarded-For", "198.51.100.1")], "192.0.2.50"),
    ],
    ids=["no-proxy", "one-hop", "spaces", "two-hops", "two-headers", "missing", "blank", "short"],
)
def test_client_ip(
    monkeypatch: pytest.MonkeyPatch, hops: int, headers: list[tuple[str, str]], expected: str
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_hops", hops)

    assert rate_limit.client_ip(_request(headers)) == expected

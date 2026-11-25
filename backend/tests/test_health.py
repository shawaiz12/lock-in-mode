from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.exc import OperationalError

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.db import get_db_session
from lock_in_mode_api.core.redis import get_redis
from lock_in_mode_api.main import app


def _make_database_fail_with(error: Exception) -> None:
    """Swap the real DB session for one whose queries raise `error`."""

    class _FailingSession:
        async def execute(self, *args: object, **kwargs: object) -> None:
            raise error

    async def _failing_session() -> AsyncIterator[_FailingSession]:
        yield _FailingSession()

    app.dependency_overrides[get_db_session] = _failing_session


async def test_health_returns_200_when_database_is_up(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


async def test_health_says_when_redis_is_missing_but_still_answers_200(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Without Redis the app works, but sign-in rate limiting is off (ADR 0008). The deploy
    # job reads "redis" and fails the deploy (ADR 0031): found going live, when a wrong
    # REDIS_URL switched rate limiting off with no sign anywhere but the logs.
    app.dependency_overrides[get_redis] = lambda: Redis.from_url(
        "redis://localhost:1/0", socket_connect_timeout=1, socket_timeout=1
    )

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "unavailable"}
    assert "Redis unreachable, rate limiting is off" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("connection refused"),
        TimeoutError("connect timed out"),
        OperationalError("SELECT 1", None, Exception("server closed the connection")),
    ],
    ids=["refused", "timeout", "dropped-mid-query"],
)
async def test_health_returns_503_when_database_is_unreachable(
    client: AsyncClient, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    _make_database_fail_with(error)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "database_unavailable"
    assert "Health check failed" in caplog.text


async def test_health_does_not_hide_unexpected_errors(client: AsyncClient) -> None:
    _make_database_fail_with(RuntimeError("bug in our code"))

    with pytest.raises(RuntimeError, match="bug in our code"):
        await client.get("/health")


async def test_live_check_says_ok_and_which_version_runs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_version", "abc1234")

    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "abc1234"}


async def test_live_check_never_touches_the_database(client: AsyncClient) -> None:
    # The platform calls it every few seconds. If it used the database, hosted Postgres
    # could never sleep and the free plan's hours would run out (ADR 0028).
    _make_database_fail_with(ConnectionRefusedError("database is down"))

    response = await client.get("/health/live")

    assert response.status_code == 200
    assert (await client.get("/health")).status_code == 503  # the full check does notice

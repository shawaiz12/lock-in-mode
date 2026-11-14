from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from lock_in_mode_api.core.db import get_db_session
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
    assert response.json() == {"status": "ok", "database": "ok"}


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

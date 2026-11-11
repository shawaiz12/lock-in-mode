from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import AsyncClient

from lock_in_mode_api.core.db import get_db_session
from lock_in_mode_api.main import app


class _UnreachableDbSession:
    """Fake session: every query fails the way a stopped Postgres would."""

    async def execute(self, *args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("simulated: database is down")


async def _unreachable_db_session() -> AsyncIterator[_UnreachableDbSession]:
    yield _UnreachableDbSession()


@pytest.fixture
def database_down() -> Iterator[None]:
    app.dependency_overrides[get_db_session] = _unreachable_db_session
    yield
    app.dependency_overrides.pop(get_db_session, None)  # always clean up


async def test_health_returns_200_when_database_is_up(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.usefixtures("database_down")
async def test_health_returns_503_when_database_is_down(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
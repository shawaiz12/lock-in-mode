from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from lock_in_mode_api.main import app
from collections.abc import AsyncIterator, Iterator


@pytest.fixture(autouse=True)
def _reset_dependency_overrides() -> Iterator[None]:
    """Runs around every test: no override can leak into the next test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client that calls the app in memory, with no real server."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
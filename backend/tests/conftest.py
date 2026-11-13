"""Shared test fixtures.

Tests never touch the dev database. They run against `lockin_test`, which is
dropped, recreated and migrated at the start of every test run.
"""

import os

# Must happen BEFORE importing the app: `settings` and `engine` are created at
# import time, so this is our only chance to point them at the test database.
# Real environment variables beat values from .env in pydantic-settings.
os.environ["POSTGRES_DB"] = "lockin_test"
# A fixed, test-only signing key, so tests never depend on the developer's .env.
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-used-anywhere-else"

import asyncio  # noqa: E402
from collections.abc import AsyncIterator, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from lock_in_mode_api.core.config import settings  # noqa: E402
from lock_in_mode_api.core.db import engine  # noqa: E402
from lock_in_mode_api.main import app  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def _recreate_test_database() -> None:
    """Drop and create the test database from the `postgres` maintenance DB."""
    name = settings.postgres_db
    admin_engine = create_async_engine(
        settings.database_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",  # CREATE/DROP DATABASE can't run in a transaction
    )
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> None:
    """Once per test run: fresh test database, migrated to the latest schema."""
    # Safety net: this fixture DROPS a database. Never let it be the dev one.
    assert settings.postgres_db.endswith("_test"), (
        f"Refusing to run tests against {settings.postgres_db!r}"
    )
    asyncio.run(_recreate_test_database())
    command.upgrade(Config(str(ALEMBIC_INI)), "head")


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


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session whose changes are all rolled back when the test ends."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()

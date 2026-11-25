import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import Depends, FastAPI
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from lock_in_mode_api.api import v1
from lock_in_mode_api.api.deps import DbSession
from lock_in_mode_api.api.errors import DatabaseUnavailable, add_problem_handlers
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.db import engine
from lock_in_mode_api.core.redis import get_redis, redis_client
from lock_in_mode_api.services.account import run_cleanup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The hourly cleanup of deleted accounts (ADR 0024) runs inside this process.
    cleanup = None
    if settings.account_cleanup_interval_seconds > 0:
        cleanup = asyncio.create_task(
            run_cleanup(settings.account_cleanup_interval_seconds), name="account-cleanup"
        )
    yield  # app runs here
    if cleanup is not None:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup
    await engine.dispose()  # on shutdown: close all pooled connections
    await redis_client.aclose()


app = FastAPI(title="Lock In Mode API", version="0.1.0", lifespan=lifespan)
add_problem_handlers(app)
app.include_router(v1.router)


@app.get("/health/live", tags=["infrastructure"])
async def live() -> dict[str, str]:
    """Is the API up, and which commit does it run? Never touches the database.

    The deploy job (ADR 0028, 0031) asks this every 10 seconds until the new commit is
    live: cheap for any host, and it can't fail just because the database is slow.
    """
    return {"status": "ok", "version": settings.app_version}


@app.get("/health", tags=["infrastructure"])
async def health(session: DbSession, redis: Annotated[Redis, Depends(get_redis)]) -> dict[str, str]:
    """Is the API up, can it reach the database, and is Redis there? For deploy checks.

    No database is an error (503): nothing works without it. No Redis still answers 200
    with "redis": "unavailable": the app works, but sign-in rate limiting is off (ADR 0008).
    The deploy job treats that as a failed deploy (ADR 0031).
    """
    try:
        await session.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError) as exc:
        # OSError: couldn't connect (refused, timeout, DNS).
        # SQLAlchemyError: connected, but the driver failed (auth, dropped connection).
        logger.warning("Health check failed: database unreachable", exc_info=exc)
        raise DatabaseUnavailable from exc
    redis_state = "ok"
    try:
        await redis.ping()
    except (RedisError, OSError):
        logger.warning("Health check: Redis unreachable, rate limiting is off", exc_info=True)
        redis_state = "unavailable"
    return {"status": "ok", "database": "ok", "redis": redis_state}

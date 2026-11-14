import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from lock_in_mode_api.api import v1
from lock_in_mode_api.api.deps import DbSession
from lock_in_mode_api.api.errors import DatabaseUnavailable, add_problem_handlers
from lock_in_mode_api.core.db import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield  # app runs here
    await engine.dispose()  # on shutdown: close all pooled connections


app = FastAPI(title="Lock In Mode API", version="0.1.0", lifespan=lifespan)
add_problem_handlers(app)
app.include_router(v1.router)


@app.get("/health", tags=["infrastructure"])
async def health(session: DbSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError) as exc:
        # OSError: couldn't connect (refused, timeout, DNS).
        # SQLAlchemyError: connected, but the driver failed (auth, dropped connection).
        logger.warning("Health check failed: database unreachable", exc_info=exc)
        raise DatabaseUnavailable from exc
    return {"status": "ok", "database": "ok"}

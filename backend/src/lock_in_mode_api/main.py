import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.db import engine, get_db_session

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield  # app runs here
    await engine.dispose()  # on shutdown: close all pooled connections


app = FastAPI(title="Lock In Mode API", version="0.1.0", lifespan=lifespan)

# Reusable dependency: any endpoint that takes `session: DbSession` gets a request-scoped session.
type DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@app.get("/health")
async def health(session: DbSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    # Fixed the indentation so it aligns perfectly with 'try'
    except (OSError, SQLAlchemyError) as exc:
        # OSError: couldn't connect (refused, timeout, DNS).
        # SQLAlchemyError: connected, but the driver failed (auth, dropped connection).
        logger.warning("Health check failed: database unreachable", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "ok", "database": "ok"}
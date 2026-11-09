from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.db import engine, get_db_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield  # app runs here
    await engine.dispose()  # on shutdown: close all pooled connections


app = FastAPI(title="Lock In Mode API", version="0.1.0", lifespan=lifespan)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@app.get("/health")
async def health(session: DbSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "ok", "database": "ok"}
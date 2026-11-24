from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lock_in_mode_api.core.config import settings

engine = create_async_engine(
    settings.database_url,
    # Checks a pooled connection before using it. Hosted Postgres (Neon) closes idle
    # connections when it sleeps (ADR 0028); this quietly replaces them.
    pool_pre_ping=True,
    connect_args=settings.database_connect_args,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

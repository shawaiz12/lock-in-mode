from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from lock_in_mode_api.core.config import settings

pool_options: dict[str, Any]
if settings.postgres_transaction_pooler:
    # Behind a transaction pooler (ADR 0031) the pooler does the pooling: a fresh,
    # cheap connection to it per request. A pool of our own inside a serverless
    # instance would hold connections while the instance sleeps, and they go stale.
    pool_options = {"poolclass": NullPool}
else:
    # Our own pool. pre_ping checks a pooled connection before using it, and quietly
    # replaces it if the server closed it meanwhile (restart, idle timeout).
    pool_options = {"pool_pre_ping": True}

engine = create_async_engine(
    settings.database_url,
    connect_args=settings.database_connect_args,
    **pool_options,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

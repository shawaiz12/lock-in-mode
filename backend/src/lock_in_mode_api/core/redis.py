"""One shared async Redis client for the app (like `engine` in core/db.py).

redis-py keeps a connection pool inside the client, so creating it here costs
nothing: no connection is opened until the first command.
"""

from redis.asyncio import Redis

from lock_in_mode_api.core.config import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    # Fail fast: if Redis is slow or down, callers decide what to do (ADR 0008:
    # rate limiting lets the request through rather than hanging sign-in).
    socket_connect_timeout=1,
    socket_timeout=1,
)


def get_redis() -> Redis:
    """FastAPI dependency, so tests can swap in a broken or separate client."""
    return redis_client

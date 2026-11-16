"""Per-IP rate limiting with a Redis fixed-window counter (ADR 0008).

How it works, for `limit = 20` per minute:

    key = "rl:guest:203.0.113.7:29384751"      <- scope, client IP, minute number
    INCR key     -> 1, 2, 3 ... (Redis creates it at 0 if missing)
    EXPIRE key   -> Redis deletes it after the minute, so nothing piles up
    count > 20   -> 429 rate_limited, with Retry-After = seconds until the next minute

Next minute, the minute number changes, so it's a new key starting from 1.
Known trade-off: someone can send 20 at 0:59 and 20 more at 1:00 (2x in a short burst).
That's fine here: the goal is stopping scripts, not exact quotas.
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from lock_in_mode_api.api.errors import RateLimited
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.redis import get_redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

# Tests replace this to move time forward without sleeping.
clock: Callable[[], float] = time.time


def client_ip(request: Request) -> str:
    # Locally this is the real caller. Behind Render's proxy it needs proxy-header
    # config at deploy time first (ADR 0008), or every user would share the proxy's IP.
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows `auth_rate_limit_per_minute` calls per IP.

    Use it on a route:  @router.post("/guest", dependencies=[Depends(rate_limit("guest"))])
    Each scope counts separately, so hitting the guest limit doesn't block Google sign-in.
    """

    async def check(request: Request, redis: Annotated[Redis, Depends(get_redis)]) -> None:
        now = clock()
        window = int(now // WINDOW_SECONDS)
        key = f"rl:{scope}:{client_ip(request)}:{window}"

        try:
            # Both commands go to Redis in one round trip. INCR is atomic, so two
            # requests arriving together can never both read "19" and both pass.
            async with redis.pipeline(transaction=False) as pipe:
                pipe.incr(key)
                pipe.expire(key, WINDOW_SECONDS)
                count, _ = await pipe.execute()
        except (RedisError, OSError):
            # Fail open: a Redis outage must not block every sign-in. We lose abuse
            # protection for that time, which is the smaller problem.
            logger.warning("Rate limiting skipped: Redis unavailable", exc_info=True)
            return

        if count > settings.auth_rate_limit_per_minute:
            seconds_left = math.ceil((window + 1) * WINDOW_SECONDS - now)
            raise RateLimited(
                "Too many attempts. Please wait a moment and try again.",
                headers={"Retry-After": str(seconds_left)},
            )

    return check

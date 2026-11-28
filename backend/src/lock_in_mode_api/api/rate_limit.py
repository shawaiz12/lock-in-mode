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

from lock_in_mode_api.api.deps import CurrentUser
from lock_in_mode_api.api.errors import RateLimited
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.redis import get_redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

# Tests replace this to move time forward without sleeping.
clock: Callable[[], float] = time.time


def client_ip(request: Request) -> str:
    """The caller's IP, for per-IP limits (ADR 0008, ADR 0028).

    Locally (TRUSTED_PROXY_HOPS=0) the connection comes straight from the caller.
    Hosted, it comes from the platform's proxy, which appends the address it saw:

        X-Forwarded-For: 6.6.6.6, 203.0.113.7
                         ^ typed by the caller  ^ added by our proxy (trust this one)

    Each trusted proxy appends one entry, so with N hops the caller is the Nth from the
    end. Anything earlier can be made up, so a script can't dodge the limit by sending
    a new fake address each time. A missing or short header means the request didn't
    come through the proxy as expected: fall back to the connection's address.
    """
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_hops
    if hops == 0:
        return peer
    # Several X-Forwarded-For headers count as one comma-separated list (RFC 9110).
    entries = [
        entry.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for entry in header.split(",")
        if entry.strip()
    ]
    if len(entries) < hops:
        return peer
    return entries[-hops]


async def _count(redis: Redis, key: str, window_seconds: int) -> int | None:
    """Add one to this window's counter and return it. None: Redis is down."""
    try:
        # Both commands go to Redis in one round trip. INCR is atomic, so two
        # requests arriving together can never both read "19" and both pass.
        async with redis.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            count, _ = await pipe.execute()
    except (RedisError, OSError):
        # Fail open: a Redis outage must not block every request. We lose abuse
        # protection for that time, which is the smaller problem.
        logger.warning("Rate limiting skipped: Redis unavailable", exc_info=True)
        return None
    return int(count)


def rate_limit(scope: str) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows `auth_rate_limit_per_minute` calls per IP.

    Use it on a route:  @router.post("/guest", dependencies=[Depends(rate_limit("guest"))])
    Each scope counts separately, so hitting the guest limit doesn't block Google sign-in.
    """

    async def check(request: Request, redis: Annotated[Redis, Depends(get_redis)]) -> None:
        now = clock()
        window = int(now // WINDOW_SECONDS)
        count = await _count(redis, f"rl:{scope}:{client_ip(request)}:{window}", WINDOW_SECONDS)
        if count is not None and count > settings.auth_rate_limit_per_minute:
            seconds_left = math.ceil((window + 1) * WINDOW_SECONDS - now)
            raise RateLimited(
                "Too many attempts. Please wait a moment and try again.",
                headers={"Retry-After": str(seconds_left)},
            )

    return check


HOUR_SECONDS = 3600


async def export_rate_limit(user: CurrentUser, redis: Annotated[Redis, Depends(get_redis)]) -> None:
    """ "Download my data" (ADR 0027): `export_rate_limit_per_hour` per account per clock
    hour. Counted per account, not per IP: it protects the database, not sign-in."""
    now = clock()
    window = int(now // HOUR_SECONDS)
    count = await _count(redis, f"rl:export:{user.id}:{window}", HOUR_SECONDS)
    limit = settings.export_rate_limit_per_hour
    if count is not None and count > limit:
        seconds_left = math.ceil((window + 1) * HOUR_SECONDS - now)
        minutes = max(1, math.ceil(seconds_left / 60))
        raise RateLimited(
            f"You can download your data {limit} times an hour. "
            f"Try again in {minutes} minute{'' if minutes == 1 else 's'}.",
            headers={"Retry-After": str(seconds_left)},
        )


async def waitlist_join_limit(
    request: Request, redis: Annotated[Redis, Depends(get_redis)]
) -> None:
    """Joining the waitlist (ADR 0037): `waitlist_joins_per_ip_per_hour` per IP per clock
    hour, on top of the per-minute limit. It stops a script inventing friends to climb
    the line; the top of the line is still checked by hand before early access goes out."""
    now = clock()
    window = int(now // HOUR_SECONDS)
    count = await _count(redis, f"rl:waitlist-hour:{client_ip(request)}:{window}", HOUR_SECONDS)
    if count is not None and count > settings.waitlist_joins_per_ip_per_hour:
        seconds_left = math.ceil((window + 1) * HOUR_SECONDS - now)
        raise RateLimited(
            "Too many signups from this network. Please try again later.",
            headers={"Retry-After": str(seconds_left)},
        )

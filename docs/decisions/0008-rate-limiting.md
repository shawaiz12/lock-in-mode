# 0008 – Rate limiting sign-in: our own Redis fixed-window dependency

**Date:** 2026-11-16
**Status:** Accepted

## Context
`POST /auth/guest` needs no account. A script could call it 100,000 times and fill the
database with fake users. `/auth/google` and `/auth/apple` can be hammered the same way,
for example to try stolen or forged tokens. We need "at most N calls per client per time
window" on these endpoints, shared across every API process, so the count lives in Redis
(already in our stack for Celery later).

Constraints:
- Many of our users are on Pakistani mobile networks, where carriers put many phones
  behind one shared public IP (CGNAT). A strict per-IP limit would block real people.
- Zero cost: hosted Redis is Upstash's free tier (500K commands/month, 256 MB, checked
  November 2026), so commands per request matter.

## Options considered

### A. The `slowapi` library
- ✅ Least code; well known (a port of Flask-Limiter, built on the `limits` library).
- ❌ Decorator style with a required `request: Request` parameter on every route, unlike
  the dependency injection we use everywhere else.
- ❌ Its 429 has to be converted into our problem format (ADR 0007).
- ❌ "How does your rate limiter work?" gets answered with "the library does it".

### B. Our own FastAPI dependency, fixed-window counter in Redis (chosen)
One key per scope, client IP and minute, e.g. `rl:guest:203.0.113.7:29384751`.
Each request: `INCR` (atomic) and `EXPIRE 60`, sent together in one round trip.
Count above the limit → 429.
- ✅ ~40 lines we can explain completely; a normal dependency (`Depends(rate_limit("guest"))`).
- ✅ Native problem-details 429 with `Retry-After`.
- ✅ 2 Redis commands per limited request.
- ❌ Edge burst: up to 2× the limit across a minute boundary (20 at 0:59, 20 at 1:00).
  Irrelevant for stopping scripts; it would matter for exact paid quotas.

### C. Our own dependency, token bucket / GCRA in a Lua script
- ✅ Smooth, no edge burst, one key.
- ❌ Harder to explain; Lua inside Redis. Its precision isn't needed here.

## Decision
**Option B.**

- `api/rate_limit.py`: `rate_limit(scope)` builds a dependency. It's attached as a
  route-level dependency on `/auth/guest`, `/auth/google`, `/auth/apple`, so it runs
  before the body is read or a token verified. Failed attempts count too.
- Each endpoint has its own counter (scope); hitting the guest limit doesn't block Google.
- Limit: `AUTH_RATE_LIMIT_PER_MINUTE`, default **20 per IP per minute**: generous because
  of shared mobile IPs. Easy to tune from real traffic later.
- Over the limit: 429 `rate_limited` problem (ADR 0007) with `Retry-After` = seconds
  until the next window.
- **Fail open:** if Redis is down or slow (1 s timeouts), the request goes through and a
  warning is logged. A Redis outage shouldn't block every sign-in; losing abuse
  protection for that time is the smaller problem.
- `/auth/refresh` is not limited: refresh tokens are 256 random bits, so guessing is
  hopeless. `/me/link/*` already requires a signed-in user.
- Configuration: `REDIS_URL` (hosted Redis gives a URL). Compose points the API at the
  `redis` service.
- Tests use a real Redis (database 15, emptied before each test), like the real test
  database in ADR 0004. CI runs a Redis service container. A pinned fake clock makes
  window tests exact.

## Consequences
- ✅ Scripts can't mass-create guests or hammer provider sign-in.
- ✅ Same pattern can protect future endpoints (e.g. squad invite codes) with a new scope.
- ⚠️ **Deploy-time requirement (Render):** the limiter keys on `request.client.host`.
  Behind Render's proxy that's the proxy's address unless uvicorn is told to trust proxy
  headers. Render's proxy appends to `X-Forwarded-For` without removing what the client
  sent, so the *leftmost* entry is spoofable: trust only the hops Render adds (count
  from the right). Configure and test this when deploying (Phase 3).
- ⚠️ Shared-IP users share a budget. If real users hit 429s, raise the limit or add a
  per-device key alongside the IP.
- ⚠️ While Redis is down, there is no rate limiting (logged).
- 🔁 Easy to change: swapping the algorithm only touches `api/rate_limit.py`.

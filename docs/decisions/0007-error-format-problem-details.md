# 0007 – Error responses: RFC 9457 Problem Details with a stable `code`

**Date:** 2026-11-14
**Status:** Accepted

## Context
Errors came back in different shapes, and none of them gave the app something reliable
to branch on:

```json
{ "detail": "This Google account already belongs to another user" }
{ "detail": [ { "type": "missing", "loc": ["body", "nonce"], "msg": "Field required", "input": {...} } ] }
```

- The app must tell the two 409s on `/me/link/*` apart (ADR 0006): one means "warn the
  user", the other means "don't offer this again". Matching English text is fragile.
- FastAPI's default 422 echoes the submitted `input`, which can contain ID tokens or
  nonces: the same leak `hide_input_in_errors` already blocks for settings.
- `detail` was sometimes a string and sometimes a list.

## Options considered

### A. Keep FastAPI's `{"detail": ...}` and put a code inside it
- ✅ Smallest change.
- ❌ `detail` would be a string, an object or a list depending on the error.

### B. Our own envelope: `{"error": {"code", "message", "fields"}}`
- ✅ Simple and common.
- ❌ A home-made format that we have to explain and document ourselves.

### C. RFC 9457 Problem Details + a `code` extension (chosen)
- ✅ A published standard (`application/problem+json`): `type`, `title`, `status`,
  `detail`, and extension members allowed. Generic clients and tools understand it.
- ✅ Same idea as ASP.NET Core's built-in `ProblemDetails`.
- ❌ A few more fields than B.

## Decision
**Option C.**

- Every error, ours or the framework's, is a problem document served as
  `application/problem+json`:
  `type` (link to the code's entry in `docs/errors.md`), `title`, `status`, `code`,
  and `detail` when it adds something beyond the title.
- **Clients branch on `code`**, a stable snake_case string. `title`/`detail` may change.
- Routes and dependencies raise subclasses of `ApiError` (`api/errors.py`), one per code,
  each holding its status, code, title and headers. Services keep raising their own
  domain exceptions; routes translate them, so services stay HTTP-free.
- Handlers cover `ApiError`, FastAPI/Starlette `HTTPException` (404 → `not_found`,
  405 → `method_not_allowed`, keeping headers like `Allow`), validation errors
  (422 → `validation_failed` plus an `errors` list of
  `{location, field, code, message}`, **never** the submitted input), and any unexpected
  exception (500 → `internal_error`, no internals in the response; the traceback is
  still logged).
- 401s keep `WWW-Authenticate: Bearer`.
- `docs/errors.md` lists every code; a test fails if a code is missing from it.
- OpenAPI documents a 422 `ValidationProblem` and a `default` `Problem` for every v1
  endpoint.

## Consequences
- ✅ The app needs one error parser, and branches on `code`.
- ✅ No secrets echoed in validation errors; no internals in 500s.
- ⚠️ `type` links point at the GitHub docs page for now. They may move to the app's own
  domain later, which is fine because clients match on `code`, not `type`.
- ⚠️ FastAPI also lists `application/json` next to `application/problem+json` in the
  OpenAPI docs (it adds the route's default media type). Harmless: same schema.
- ⚠️ Adding a code means adding a class *and* a docs entry (the test enforces the second).
- 🔁 Reversible: the shape is produced in one module.

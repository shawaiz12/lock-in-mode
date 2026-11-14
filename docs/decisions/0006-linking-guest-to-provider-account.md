# 0006 – Saving a guest's progress: a separate "link" endpoint

**Date:** 2026-11-14
**Status:** Accepted
**Builds on:** [0005 – Authentication](0005-authentication-tokens.md), Decision 3

## Context
ADR 0005 decided *what* happens when a guest signs in with Google or Apple:

- the Google/Apple account is new → the guest is upgraded and keeps all progress;
- the account already belongs to another user → sign into that account, and this
  device's guest progress is not carried over, **after the app warns the user**.

It did not decide *how* the backend knows that a sign-in is a guest saving progress,
or how the app finds out in time to show that warning.

## Options considered

### A. One endpoint does both
`POST /auth/google` also accepts the guest's access token in the `Authorization` header.
With it, the server upgrades the guest or switches accounts on its own.
- ✅ One call for the app.
- ❌ The server acts before the app can warn, which breaks the "warn first" rule.
- ❌ The same endpoint behaves differently depending on an optional header.

### B. A separate link endpoint (chosen)
`POST /api/v1/me/link/google` and `/me/link/apple` require the user's access token.
- The account is new → the provider id is attached, `is_guest` becomes false. **200**.
- The account already belongs to another user → **409 Conflict**, nothing changes.
  The app shows the warning; if the user confirms, it calls `POST /auth/google`.
- ✅ Each endpoint has one job: `/auth/*` signs in, `/me/link/*` attaches.
- ✅ The 409 is exactly the "pause and warn" signal ADR 0005 needs.
- ✅ The user id doesn't change, so the guest's existing tokens keep working.
- ✅ Also lets a Google user add Apple later (same endpoint, no extra code).
- ❌ The app handles one more response (409).

### C. Guest refresh token in the request body
- ❌ Mixes two credentials in one request and spreads the refresh token, our most
  sensitive token, to another endpoint.

## Decision
**Option B.**

| Request | Situation | Response |
|---|---|---|
| `POST /auth/{google,apple}` | provider account known | 200, tokens for that user |
| | provider account new | 200, new non-guest user + tokens |
| `POST /me/link/{google,apple}` | provider account new | 200, user (now `is_guest: false`) |
| | already linked to *this* user | 200 (safe to retry) |
| | belongs to another user | 409 |
| | this user already has a *different* account of that provider | 409 |
| any of the above | ID token invalid / wrong nonce | 401 |
| | provider not configured on the server | 503 |

Apple requests must include the raw `nonce` (ADR 0005).

**Race condition:** two requests can link the same Google account at the same moment.
Instead of "check, then write" (both checks pass, both write), we let the database
decide: `users.google_sub` / `users.apple_sub` are `UNIQUE`, so the second write fails
and becomes a 409. First sign-ins use `INSERT ... ON CONFLICT DO NOTHING` for the same
reason: two simultaneous first sign-ins end up as one user.

## Consequences
- ✅ The app is always the one to tell users they're about to leave guest progress behind.
- ✅ No migration needed: the unique constraints already exist.
- ⚠️ A guest that is left behind (409 → sign in elsewhere) stays in the database with
  no way back in. A cleanup job for old orphaned guests is a later Celery task.
- ⚠️ Unlinking a provider is not supported yet (not needed for the MVP).
- 🔁 Easy to change: the link endpoints are additive; option A could be added later
  without breaking these.

# 0027 – Guest sign-in life, lost guests, and "Download my data"

**Date:** 2026-11-24
**Status:** Accepted

## Context
Two small stages built together (user's choice, to pick up the pace: one decision round,
build straight after).

**Guests.** Found in ADR 0026: a refresh token lasts 60 days from its last use (ADR 0005).
A guest's token is their only way back in, so a guest who doesn't open the app for 60
days loses everything for good, while the comeback rules (ADR 0021) expect long breaks.
Separately, a guest can end up with no usable token at all (signed out, or locked out
when a stolen token was reused): nobody can ever open that account again, but its rows
stay forever ("orphaned guests" on the Later list).

**Data export.** ADR 0024 erases on request and ADR 0025 records usage events; the right
of access and portability (GDPR art. 15 and 20) still needs "Download my data". There is
no file storage, no worker and no email service, and one person's data is small (a heavy
year is about 1 MB).

What the code gives us (main `8bcce33`): `_issue_token_pair` sets one expiry for everyone;
the hourly cleanup (ADR 0024) runs inside the API; the Redis limiter (ADR 0008) counts
per IP per minute; a test already lists every table that belongs to a user.

## Decisions

### 1. A guest's sign-in lasts a year from its last use (user's choice)
New setting `GUEST_REFRESH_TOKEN_TTL_DAYS` (365). Every refresh renews it, so only a
year without opening the app signs a guest out. Google/Apple accounts keep 60 days: they
can always sign in again. Guest or not is read at each refresh, so a guest who links
Google/Apple gets the account's 60 days from their next refresh.
- ❌ "Never expires" was rejected: a copied token would work forever, and abandoned
  guests could never be cleaned up.
- ❌ "Keep 60 days, warn in the app" was rejected: a phone can't warn someone who isn't
  opening the app.
- Reuse detection (ADR 0005) is unchanged, so a stolen guest token is still locked out
  the moment both copies are used.

### 2. Lost guests are erased by the hourly cleanup (user's choice)
A guest is lost when they have no refresh token that still works: unused (the newest of
its family), not revoked, and not expired. The hourly cleanup now also erases those, in
batches of 200 with `FOR UPDATE SKIP LOCKED`, the same way as due deletions.
- **A day's margin, twice:** a token counts as working until a day after its expiry (the
  expiry is set by the app's clock, the check uses the database's), and a guest made
  less than a day ago is never touched.
- Everything goes with them (the CASCADEs from ADR 0024). No leaving reason, no event:
  like a guest deleting themselves.
- **Signing a guest out now erases them within about an hour.** It always meant losing
  the account; now the data goes too. The app must say so before a guest signs out
  ("Sign in with Google/Apple first, or this account and its progress are gone").
- ❌ "Keep them" was rejected: rows nobody can ever open again, kept forever.

### 3. One JSON file, straight away (user's choice)
`GET /me/export` returns `lock-in-mode-data.json` (`Content-Disposition: attachment`,
`Cache-Control: no-store`). Guests can use it too.
- **In it:** `format`, `version` (1), `exported_at`; `account` (with `signed_in_with`:
  `["google"]`, `["apple"]`, both or none); `profile` (every answer, including limits and
  the low-intensity flag: it's their data); `plans` with their `workouts` and each
  workout's `exercises`; `workout_sessions` with their `sets`; `strength_test`;
  `exercise_progress`; `interval_progress`; `swapped_out_exercises`; `comebacks`;
  `usage_events`. Exercises appear by name, never by id.
- **Not in it:** `refresh_tokens` (only hashes: security internals) and the Google/Apple
  account ids. Leaving reasons aren't linked to anyone, so they can't be found.
- **A new table can't be forgotten:** each table is read with a plain SELECT of all its
  columns, so new columns come along by themselves, and a test fails if a new user table
  is neither exported nor named as not exported.
- An account waiting to be deleted is signed out (ADR 0024), so the app should offer
  "Download my data" on the delete screen, before the user confirms.
- ❌ "Training data only" was rejected: it isn't "all my data".
- ❌ "Background job + link" was rejected: storage and a worker cost money, for a file
  built in well under a second.

### 4. Three downloads per account per clock hour (user's choice)
A fourth gets 429 `rate_limited`, `Retry-After`, and a `detail` ready to show: "You can
download your data 3 times an hour. Try again in 40 minutes." Counted per account (not
per IP) in Redis, like the sign-in limits; if Redis is down the limit is skipped (fail
open, ADR 0008). New setting `EXPORT_RATE_LIMIT_PER_HOUR` (3).
- ❌ "No limit" was rejected: one buggy app loop could keep the database busy.
- ❌ "Once a day" was rejected: a failed download on a bad connection locks them out.

## API
- `GET /me/export` (new): the file, or 429 `rate_limited`.
- `POST /auth/guest` and `/auth/refresh` for guests: refresh tokens last 365 days.
- No other changes; `docs/errors.md` notes the export limit under `rate_limited`.

## Data
No migration (`uv run alembic check`: "No new upgrade operations detected.").

## Consequences
- ✅ Guests survive long breaks; abandoned guests stop piling up; every user can take
  all their data with them. No new service, no cost.
- ⚠️ A guest who signs out is erased within about an hour (decision 2): the app's
  sign-out screen must warn guests.
- ⚠️ A stolen guest token stays usable for up to a year if the thief keeps refreshing it
  and the owner never opens the app again (reuse detection catches it the moment the
  owner does). Same trade-off as before, for longer.
- Later: the privacy policy should name the export and the lost-guest rule; Apple's
  /auth/revoke on deletion (launch must for iOS, ADR 0024).

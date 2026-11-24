# 0024 – Deleting an account

**Date:** 2026-11-24
**Status:** Accepted

## Context
Apple rejects apps that let people sign up but not delete their account from inside the
app (App Store Review Guideline 5.1.1(v)). Deleting must really delete, not just switch
the account off. It must be easy to find, and the app must say how long it takes. Apps that
offer Sign in with Apple should also tell Apple to cancel its tokens (`/auth/revoke`).

What the code already gives us (checked on main `7ef48e3`):
- Every table that belongs to a user points at `users.id` with `ON DELETE CASCADE`:
  profiles, plans (→ workouts → planned exercises), workout sessions (→ set logs, movement
  rungs), exercise targets, interval steps, swaps, comebacks, refresh tokens. Deleting
  the `users` row removes all of it in one statement.
- `workout_sessions.comeback_id → comebacks.id` has no `ON DELETE` rule. Both sides cascade
  from the same user in the same statement, so Postgres accepts it; a test proves it.
- Nothing about a user lives in Redis (only rate-limit counters keyed by IP).
- `get_current_user` already answers 401 when a valid access token's user no longer
  exists.
- The API runs as one process (`uvicorn` without `--workers`); tests call the app through
  `ASGITransport`, which never starts the app's lifespan.
- No job runner exists yet (no Celery, no cron). On Render's free plan the API sleeps after
  15 minutes without traffic, and Render's cron jobs cost money (at least $1/month each).

## Decisions

### 1. Linked accounts are deleted after 30 days (user's choice, no extra cost)
`DELETE /me` on a Google/Apple account:
- sets `users.delete_after = now() + 30 days` (database clock),
- revokes **every** refresh token of the user (signed out on every device),
- answers **202 Accepted** with `{"delete_after": "<timestamp>"}` so the app can say
  "Your account will be deleted on 24 Dec. Sign in before then to cancel."

While an account waits, its access tokens stop working right away: `get_current_user`
treats a waiting account like a deleted one (401 `invalid_access_token`), so an access
token can't outlive the request by up to 15 minutes.
- ❌ "Right away for everyone" was the first recommendation. Shawaiz chose 30 days if it
  costs nothing. It costs no money (decision 4), only a bigger stage.

### 2. Guests are deleted right away (user's choice)
A guest's only way back in is the refresh token on that phone. Once signed out they could
never cancel, so waiting would only keep their data longer. `DELETE /me` on a guest
deletes the user row at once and answers **204 No Content**.

### 3. Everything is erased (user's choice)
When the time comes, the `users` row is deleted and the cascade takes everything with it.
No anonymous training data is kept. The only thing left is the optional leaving reason
(decision 6), which has no link to the person.
- ❌ "Keep anonymous training stats" was rejected: nothing uses them yet, and stripped
  workout logs can still point back to a person.

### 4. Cleanup runs inside the API, and sign-in never trusts a late cleanup
- **Hourly cleanup:** when the API starts, it starts one background task that deletes due
  accounts (`delete_after <= now()`) right away and then once an hour. It deletes in
  batches of 200 with `FOR UPDATE SKIP LOCKED`: short transactions (one account can own
  thousands of set logs), and it never waits on an account that a sign-in is busy with. A
  failed run is logged and tried again next hour; it never stops the API. Setting
  `ACCOUNT_CLEANUP_INTERVAL_SECONDS=0` switches the task off (tests call the cleanup
  function directly).
- **Sign-in checks the date itself:** a sleeping server can't run its hourly task. If
  someone signs in with Google/Apple after `delete_after` has passed but before the
  cleanup ran, the old account is deleted first and a brand-new account is created. To
  the user, the account is always gone on time.
- **Linking checks it too:** a guest linking a Google/Apple account whose old account is
  past its date deletes that old account first, so the link works instead of a 409.
- All time comparisons use the database clock (`now()`), never the app's clock.
- ❌ A Render cron job was rejected: it costs money. ❌ Celery was rejected: a worker
  service for one hourly query.

### 5. Signing in during the 30 days cancels the deletion (user's choice)
`POST /auth/google` or `/auth/apple` for a waiting account clears `delete_after` (and the
reason), signs in as usual and returns `"deletion_cancelled": true` in the token reply
(otherwise `false`), so the app can say "Welcome back, your account won't be deleted."
Everything is still there. If they were away 2+ weeks, the comeback rules (ADR 0021) apply
as after any break: that clock counts from the last ticked set.
- ❌ "Ask first" was rejected: one more screen and endpoint, for people who signed in
  on purpose.

### 6. Optional "Why are you leaving?", stored anonymously (user's choice)
`DELETE /me?reason=<too_hard|no_time|injury|switched_apps|privacy|other>`, optional.
- A guest's reason is saved right away.
- A linked account's reason waits on the user row (`users.deletion_reason`) and is saved
  only when the account is actually deleted, so cancelled deletions don't count as people
  who left.
- The saved row is only `reason`, `was_guest` and `left_on` (the **day** the user asked,
  no time of day) in table `account_deletion_reasons`. No user id, no plan, nothing that
  links back.

### 7. Signed in is enough to delete (user's choice)
A valid access token is enough; the app shows a clear "This can't be undone" screen first
(and for linked accounts, the date). No fresh Google/Apple sign-in.
- ❌ "Fresh Google/Apple sign-in" was rejected for now: extra work and a screen, and
  guests can't do it anyway. Apple's revoke (decision 8) will need one Apple sign-in at
  delete time for Apple accounts only.

### 8. Apple token revoke: later, required before the first iOS submission (user's choice)
Not built now. There's no iPhone app to send Apple's one-time authorization code and no
Apple key (Team ID, Key ID, `.p8`) to sign the request. Plan for then:
- `DELETE /me` gains an optional `apple_authorization_code`. The server exchanges it with
  Apple (`/auth/token`, the code expires in 5 minutes) and calls `/auth/revoke` at once.
  The `sub` stays the same, so signing in again within 30 days still cancels.
- If Apple is down, the deletion still goes ahead (Apple's own guidance: a deletion
  request must be honoured even without tokens).
- Adding an optional field doesn't break existing apps.

## API
- `DELETE /me` (query `reason` optional): **204** guest deleted now · **202**
  `AccountDeletion {delete_after}` linked account waiting. 401 as for every `/me` call.
- `TokenPair` gains `deletion_cancelled: bool` (false except on a sign-in that cancelled).
- No new error codes.

## Data
One migration (down_revision `d5d22d3c640e`):
- `users.delete_after` timestamptz NULL, with a partial index `WHERE delete_after IS NOT
  NULL` (the cleanup's lookup).
- `users.deletion_reason` text NULL, CHECK `deletion_reason IS NULL OR delete_after IS
  NOT NULL` (a reason only while waiting). Autogenerate doesn't see CHECKs on an existing
  table, so this one comes from a helper script.
- New table `account_deletion_reasons` (id, reason, was_guest, left_on date). No foreign
  keys.

## Consequences
- ✅ Meets Apple's 5.1.1(v) except the token revoke, which is written down as a launch
  must.
- ✅ No new service and no new cost. ✅ One statement erases a user, thanks to the cascades
  every user table already has.
- ⚠️ Data of a linked account stays up to 30 days after the request (plus at most an hour,
  or until the next sign-in or wake-up on a sleeping server). The app must show the date.
- ⚠️ Every new user table must keep `ON DELETE CASCADE` to `users`, or deletion breaks. A
  test deletes a user who has a row in every table and checks that nothing is left.
- Later: data export ("download my data"), Apple revoke (decision 8), Apple's
  server-to-server notifications (account deleted on Apple's side).

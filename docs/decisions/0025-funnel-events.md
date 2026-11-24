# 0025 – Funnel events: where people drop off

**Date:** 2026-11-24
**Status:** Accepted

## Context
We can't yet see where people stop: after signing up, before the first workout, after
workout 2, at the end of the first block? Fitness apps lose most people in the first
days, and the retention notes (`lock-in-mode/retention-knowledge.md`, Piggy Bank) say:
track what users do, collect only what improves the plan or the product, disclose it in
the privacy policy, and make the opt-out clear (Play and App Store data-safety forms).
Paywall tests later (Source 2) also need this.

Some of it could be pieced together from existing tables (`users.created_at`,
`workout_sessions.finished_at`, `plans.block_number`), but not everything: a link to
Google, a level-up offered and turned down, a deletion asked and then cancelled leave no
row or are erased. One timeline is also far simpler to query than joins over eight
tables.

What the code gives us (main `86714fd`):
- Every action already runs in one service function that commits once. An event written
  in the same transaction is saved only if the action is; a failed action leaves no
  event.
- The level-up offer is worked out when the plan is read (`level_up_offer` on
  `GET /plans/current`), not saved, so "offered" is recorded on the block-complete event
  instead of on every read.
- `DELETE /me` erases everything (ADR 0024); every user table cascades.

## Decisions

### 1. The server records events (user's choice)
The API writes an event when something real happens, inside the same transaction. No
`POST /events` for now: there's no app yet, and anything a client sends can be junk.
App-only moments (screen views, taps) come with the mobile app (phase 3).

### 2. Our own Postgres table (user's choice)
`events`: `id`, `user_id` (FK users, ON DELETE CASCADE), `name`, `at` (database clock,
`clock_timestamp()`: the moment the row is written, so one request's events keep their order),
`props` (small JSON). Indexes for the report: `(name, at)` and `(user_id, at)`.
Nothing leaves our server; no new service, no cost. Can be forwarded to an analytics
tool later.

### 3. Erased with the account (user's choice)
Events cascade like every other user table, so ADR 0024's promise ("everything is
erased") still holds. The funnel won't show the full path of people who deleted; their
reason is still counted anonymously (`account_deletion_reasons`).

### 4. On by default, with a "Share usage data" switch (user's choice)
- New column `users.share_usage_data` (default true), shown in `GET /me` and changed with
  `PATCH /me {"share_usage_data": false}`.
- Off: no new events, and **every past event of that user is erased** in the same request
  (user's choice). Back on: starts fresh.
- The check is inside the insert itself (`INSERT … SELECT … WHERE the user shares`), so no
  event can slip in between reading the setting and writing.
- The privacy policy must list it (Play data safety: "App activity"); see Later.

### 5. The full journey: 11 events (user's choice)
Only fixed, typed details: no free text, no health answers (the safety screen, limits
and "where it hurts" are never copied into events), no IP address, no device data.

| Event | When | Details |
|---|---|---|
| `signed_up` | a new user is created | `method`: guest / google / apple |
| `account_linked` | a guest links Google/Apple | `provider` |
| `onboarding_done` | the first safety screen is taken (profile + safety = ready) | `goal`, `level`, `location`, `days_per_week`, `minutes_per_session` |
| `plan_started` | a block is created | `block`, `level`, `reason`: first / next_block / answers_changed |
| `workout_started` | a new session starts (not "continue") | `number` (their Nth started), `kind` |
| `workout_finished` | a session is finished (also auto-finished) | `number` (their Nth finished), `kind`, `feedback` or null, `comeback` true/false |
| `block_complete` | the last workout of a block is finished or skipped (or, when a break replaced the recovery week that was left, when the next block starts) | `block`, `level_up_offered` true/false |
| `level_up_accepted` | the next block starts with "Ready for more?" = yes | `from`, `to` |
| `comeback_started` | a comeback after a break is saved (ADR 0021) | `away_days`, `weeks` |
| `deletion_requested` | a Google/Apple account asks to be deleted | — |
| `deletion_cancelled` | signing in cancels it | — |

- `block_complete` is recorded once per block, even if two requests race (a unique
  index). Found by the sweep: a block can also end by time alone, when a break replaces
  the recovery week that was left (ADR 0021); its event is then written when the next
  block starts.
- A guest's deletion is erased at once, so it gets no event (its events go with it).

### 6. A terminal report (user's choice)
`uv run python -m lock_in_mode_api.reports [--days 90]` prints, for users who signed up in
the last N days:
- **Funnel:** signed up → onboarding done → workout 1 finished → workout 3 finished →
  block 1 complete → block 2 started, each with how many users and the % kept from the
  step before. "Block 2 started" counts only a next block (`reason` next_block): a plan
  rebuilt after changed answers also gets block number 2 (found on the sweep's data,
  where it showed more block 2 starts than block 1 completions).
- **Weekly retention:** per sign-up week, the share who finished a workout in week 1, 2
  and 4 after signing up.
- **Other counts:** account linked, level-up offered vs accepted, deletions asked vs
  cancelled, leaving reasons (from `account_deletion_reasons`).
No new endpoint and no admin login. It reads the database the settings point at.
- ❌ "Admin API endpoint" was rejected: a new kind of login to secure; the planned Django
  admin is the better home later.

## API
- `GET /me` gains `share_usage_data`.
- `PATCH /me` becomes a true partial update: send only what changes (`display_name`,
  `share_usage_data`, or both). A field left out isn't touched; `display_name: null`
  still clears the name.
- No new endpoints, no new error codes.

## Data
One migration (down_revision `d217f3b9e345`): new table `events` (FK users CASCADE,
indexes `(name, at)` and `(user_id, at)`) and `users.share_usage_data` boolean NOT NULL
DEFAULT true. Autogenerate sees all of it; no helper script.

## Consequences
- ✅ One timeline answers "where do people stop?" with plain SQL; ready for the paywall
  tests and drop-off prediction later (brief phase 5 stretch).
- ✅ No new service, no cost, nothing sent to other companies; erased on delete and on
  opt-out.
- ⚠️ Every new feature that matters to the funnel must record its event in its own
  transaction (tests check each one).
- ⚠️ Events grow with use. Fine for years at our size; an age limit can be added to the
  hourly cleanup later.
- Later: privacy-policy text and store data-safety answers (phase 5); app events (screen
  views) with the mobile app; an age limit for old events; a dashboard in the Django admin.

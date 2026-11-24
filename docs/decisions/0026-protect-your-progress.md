# 0026 – Protect your progress: offering guests a sign-in

**Date:** 2026-11-24
**Status:** Accepted

## Context
People can train without signing in (ADR 0006, 0012). A guest's whole account lives
behind one refresh token on one phone: uninstall the app, change phones or clear its data,
and everything is gone (workouts, saved numbers, swapped-out exercises, the strength
test). The retention notes (`lock-in-mode/retention-knowledge.md`, Piggy Bank) say:
make the stored value visible ("Your plan knows you: …") and, **after a few workouts and
never before workout 1**, offer Google/Apple sign-in framed as "protect your progress".

What the code gives us (main `c98dbee`):
- Linking (`POST /me/link/{google|apple}`) keeps the same user id, so a guest who links
  simply stops being a guest. The server never has to remember a "not now" tap.
- Finishing a workout returns the finish screen (`SessionResult`, with `block_complete`).
  Some workouts end with **no** finish screen: a workout left open is closed automatically
  when a later one is started or when changed answers replace the plan, and a block can
  end with a skip.
- A plan rebuilt after changed answers also gets the next block number, so "block 1" is
  not the same as "the first block they finished". A finished block is a plan that ends
  with `end_reason = finished` when the next one starts. Changed answers can also replace
  a block that is already complete (`end_reason = answers_changed`, nothing pending).
- Everything the summary counts is already stored: `workout_sessions`, `set_logs`,
  `exercise_targets` (ADR 0019), `swapped_out_exercises` (ADR 0020), `movement_rungs`
  (ADR 0018). There is no history of each "step up", only where each exercise stands now.

## Decisions

### 1. Offered three times: after workout 3, after workout 10, at the first finished block (user's choice)
The finish screen carries the offer when, for a guest, this finish:
- completes their **first finished block** (the block is complete, and none of their
  earlier plans was complete), or
- is their **10th** finished workout, or
- is their **3rd** finished workout.

An earlier plan was complete if it ended as finished (the next block was started), or if
changed answers replaced it with no workout left pending. A plan replaced half-way doesn't
count. Found while building: counting only "ended as finished" would offer "first block"
twice to a guest who finished block 1, changed their answers and finished the new block.

If one finish hits two of these (a 2-days-a-week block ends on workout 10), it's one
offer, named by the first match in that order. Each milestone can only happen once, so
the same offer is never made twice. After the three, it's never pushed again; the
settings card (decision 2) stays. Workouts count whatever kind they are, comeback ones
included. Low-intensity guests are offered it too: signing in changes nothing about their
plan.
- ❌ "Once, after workout 3" was rejected: guests who tap "not now" are never asked again.
- ❌ "After workout 1, then every 5" was rejected: pushy straight after the strength test,
  and it never stops.
- ❌ "Only at the end of block 1" was rejected: about 15 workouts in, many guests are gone.

### 2. On the finish screen, and a summary on `GET /me` (user's choice)
- `SessionResult.sign_in_offer`: `null`, or `{milestone, summary}` on the three finish
  screens above. The app shows "Protect your progress" with Google/Apple buttons and a
  "Not now" that does nothing on the server.
- `GET /me` gains `progress_summary`: the same summary for **every guest** (even with 0
  workouts, then with no lines), `null` for Google/Apple accounts. The app can show a
  quiet "Protect your progress" card in settings at any time.
- ❌ "Finish screen only" was rejected: no way back to the summary after "not now".
- ❌ "A separate endpoint" was rejected: the app would decide when to ask, and the
  3/10/first-block rule would drift into mobile code.

### 3. The summary uses numbers we already store (user's choice)
| Field | Counted from | Line (left out when 0) |
|---|---|---|
| `workouts_finished` | finished `workout_sessions` | "7 workouts finished" |
| `sets_logged` | `set_logs` of their sessions | "96 sets logged" |
| `exercises_with_own_numbers` | `exercise_targets` rows with a weight, a set change, a hold or extra reps | "Your own numbers saved for 12 exercises" |
| `exercises_left_out` | `swapped_out_exercises` rows | "2 exercises left out because they hurt" |
| `strength_test_moves` | `movement_rungs` rows | "Strength test: starting points for 4 moves" |

Real counts only, never rounded up; "1 workout" / "1 set" / "1 exercise" / "1 move" in the
singular, and "1 exercise left out because it hurt". One query with five counts.
- Found while building: progression also saves a row that only counts missed sessions
  (`short_runs`), with every number still as planned. Those aren't "your own numbers", so
  they aren't counted: the summary never overstates.
- ❌ "Also count step-ups" was rejected: no step history exists, so it would need a new
  counter, a migration and changes to the progression code, and it would show 0 for
  everyone who has already trained.
- ❌ "Workout count only" was rejected: it doesn't show that the plan has learned anything.

### 4. Numbers and ready-made lines (user's choice)
Like the level-up "what changes" lines (ADR 0022): the server sends the numbers and
`lines`, in the table's order, leaving out lines for 0. Tests check that every line
matches its number. The app adds the heading ("Your plan knows you") and the buttons.
- ❌ "Numbers only" was rejected: the never-overstate rule would live in untested mobile
  code.

### 5. A missed milestone is not caught up (user's choice)
If workout 3 or 10 is closed automatically (the guest started a later workout without
tapping Finish, or changed answers replaced the plan), or the first block ends with a skip
or with such an automatic close, there's no finish screen, so that offer is skipped. A
block finished that way still counts as their first finished block. The settings card and the next milestone still cover it. No column
remembers which offers were made, so **no migration**.
- ❌ "Catch up on the next finish screen" was rejected: it needs a column and a migration
  for an edge case the other two asks already cover.

### 6. A 12th event: `sign_in_offered` (user's choice)
`sign_in_offered {milestone: workout_3 | workout_10 | first_block, number}` (`number` =
workouts finished), recorded in the finish transaction when the finish screen carries the
offer. Same rules as every event (ADR 0025): only while "Share usage data" is on, erased
with the account. Event names are stored as plain text: no migration.

### 7. The report: offered → linked within 7 days (user's choice)
The terminal report (`uv run python -m lock_in_mode_api.reports`) gains a "Protect your
progress" section: for each milestone, how many guests were offered it and how many
linked (`account_linked`) within 7 days after it, with the %. A link is credited to the
latest offer before it, so one link is never counted twice. A "total" line counts guests
offered at least once and guests who linked within 7 days of any offer.
- ❌ "Any time after" was rejected: it credits the prompt for links months later.
- ❌ "Same day only" was rejected: it misses people who sign in that evening.

## API
- `GET /me` gains `progress_summary` (guests) / `null` (Google/Apple accounts).
- `POST /sessions/{id}/finish` gains `sign_in_offer` (`null` or `{milestone, summary}`).
- No new endpoints, no new error codes.

## Data
No migration. One new event name (`sign_in_offered`); enums are stored as plain text.
`uv run alembic check` must say "No new upgrade operations detected."

## Consequences
- ✅ Guests are asked at the moments they have most to lose, with real numbers, and the
  report shows whether it works.
- ✅ No migration, no new service, no cost (money: none; time: one extra query on
  `GET /me` for guests and on the three finish screens).
- ⚠️ Missed milestones are skipped (decision 5); the settings card is the fallback.
- ⚠️ Found while checking the code: a guest's refresh token expires after **60 days
  without opening the app** (ADR 0005). A guest away that long is signed out for good,
  even though the comeback rules (ADR 0021) expect long breaks. The offer copy should say
  plainly that guest progress lives only on this phone.
- Later: the offer's copy and screens with the mobile app (phase 3); a longer guest token
  life or a warning before it runs out; the summary for every user as a profile stat
  (phase 4); a step-ups count if a step history is ever stored.

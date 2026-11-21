# 0017 – Saving and serving plans: blocks, the recovery week, the queue

**Date:** 2026-11-21
**Status:** Accepted (stage 3 of the plan generator, ADR 0014)

## Context
Stages 1 and 2 (ADR 0014–0016) turn onboarding answers into complete workouts, but
nothing is saved and nothing reaches the app. ADR 0014 already settled the big shape: a
"next workout" queue instead of fixed weekdays, one saved plan per training block, and a
new block when the profile changes. This ADR settles the rest, so the app can show the
plan and the next workout.

## Decisions

### 1. Every block is 4 build-up weeks and 1 recovery week, for every level (user's choice)
The Knowledge Base (section 10) builds up for 6 / 5 / 4 weeks by level before a lighter
week. The user chose one length for everyone: **4 + 1 = 5 weeks**.
- ✅ Within normal coaching practice: lighter weeks are commonly planned every 4 to 8
  weeks, most often every 4 to 6, for about a week (Bell et al. 2022, Frontiers in
  Sports and Active Living; Bell et al., NSCA practical guide to deloading).
- ✅ Simpler to explain ("every 5th week is a recovery week") and to test.
- ❌ Beginners get 2 fewer build-up weeks than the KB suggests, and new small moves every
  5 weeks instead of 7. Big lifts don't change between blocks (decision 3), so they still
  repeat long enough to learn.
- The recovery week is **saved with the block**, so the plan screen can show it from the
  start. Its workouts follow KB section 10: the same exercises, **half the sets** (rounded
  up), strength stops **4 reps short**, interval work drops **2 effort points** (not below
  3/10). Walks, steady cardio, mobility, warm-ups and cool-downs stay the same: they are
  easy already.
- The weekly "+1 set per muscle" ramp and the early lighter week after "too hard" taps
  belong to progression (next stage), which changes the saved numbers.

### 2. A finished block ends with "Block complete!" and the user starts the next one (user's choice)
When every workout is done or skipped, `GET /plans/current` says `block_complete: true`
and `GET /plans/current/next` answers 404 `block_complete`. The app celebrates and offers
a button that calls `POST /plans`.
- ✅ A moment to celebrate (and later, to give XP), and a natural point to update answers
  first ("I can train 4 days now").
- ✅ GET requests never create data. Only `POST /plans` builds a block.
- ❌ An automatic next block was rejected: no "block complete" moment, less control.

### 3. Each new block keeps the big lifts and changes the small moves
ADR 0014 promised fresh picks each block; KB section 10 says keep the main exercise in a
slot for a block or longer, and swap the lower-priority slots for variety. Both hold:
- **Big lifts** keep the same 2 alternating picks in every block, so "your dumbbell press
  went 20 → 24 kg" compares like with like.
- **Small moves** take the best 6 options for the slot, 3 at a time: block 1 uses picks
  1–3, block 2 picks 4–6, block 3 picks 1–3 again. Slots with fewer options wrap around.
- Still deterministic: the same answers and block number always give the same block.

### 4. Changing the answers replaces the plan at once (user's choice)
`PUT /me/profile` and `POST /me/safety-screen` rebuild the plan in the **same
transaction** when the new answers change it.
- ✅ Safety first: a new "yes" on the safety screen makes the plan gentle immediately.
- ✅ "3 → 4 days" takes effect now, not after weeks.
- Only answers the generator reads count. Each plan saves them (`generated_from`, see
  decision 7); if they're equal, nothing happens. Obstacles never change the plan.
- A plan the user has **already trained in** ends (`end_reason = answers_changed`) and
  stays as history; the new block gets the next block number.
- A plan **nobody has touched yet** (every workout pending) is rebuilt in place: deleted,
  with its block number reused. This is onboarding screen 13, where the shoulder-day or
  bro-split answer comes after the first plan is shown. Otherwise a new user would start
  at "block 2" before training once.
- ❌ "Ask first" (mark it out of date) was rejected: an ignored prompt could leave an
  unsafe plan in place. ❌ "Wait until the block ends" was rejected: changes would do
  nothing for weeks.

### 5. The user can skip the next workout (user's choice)
`POST /workouts/{id}/skip` marks it skipped and the queue moves on: no penalty, no
"missed" (brief 3.2, no shame). Only the **next** workout can be skipped (409
`not_next_workout` otherwise), so the queue stays a queue.
- **Skipping the strength test moves it** to the next strength workout that has test
  movements (push-up, squat, plank, pull-up). Full body B has none, so it goes to the next
  Full body A. It never moves into the recovery week; if no workout is left, the next
  block has the test instead.
- The test stays in every new block until a test workout is **done** (not skipped). The
  sessions stage sets "done".

### 6. API
| Endpoint | Does |
|---|---|
| `POST /plans` | Builds and saves the first block (after the safety screen) or the next one (after "Block complete!"). 201. 409 `safety_screen_required`, 409 `plan_in_progress`. |
| `GET /plans/current` | Reasons, suggested weekdays, the whole queue with statuses, `next_workout_id`, `block_complete`. ETag. |
| `GET /plans/current/next` | The next workout in full: warm-up, main, finisher, cool-down. ETag. |
| `GET /workouts/{id}` | Any of the user's workouts, old plans included. ETag. |
| `POST /workouts/{id}/skip` | Skip the next workout; returns the updated plan. |

The brief's `POST /plans/regenerate` isn't needed: changing the answers rebuilds the plan
by itself, and `POST /plans` starts the next block.

### 7. Tables
- **`plans`**: block number, routine, reasons, weekdays, `weeks`, `generated_from` (JSONB:
  exactly the answers the generator reads, `training.plan_types.PlanAnswers`), `ended_at`
  and `end_reason`. NULL `ended_at` = current.
  - **One current plan per user** is a partial unique index (`WHERE ended_at IS NULL`),
    so even two requests at once (a double tap on "start next block") can't create two.
    The service turns that error into 409 `plan_in_progress`.
  - Block numbers are unique per user; an ended plan must say why (CHECK).
- **`planned_workouts`**: position (queue order across the block), week, kind, title,
  format, `recovery`, minutes, status (`pending` / `done` / `skipped`).
- **`planned_exercises`**: part (warm-up, main, finisher, cool-down), position, the numbers
  (sets, reps, seconds, rest, reps in reserve, effort, group, practice sets, test).
  `exercise_id` is `ON DELETE RESTRICT` and indexed: an exercise in a saved plan can't
  be deleted from the library, and Postgres doesn't index foreign keys by itself.
- The generator's output is stored as it was made: a library change never silently
  changes a plan in progress (ADR 0014 decision 3).
- Relationships are `lazy="raise"`: async code can't load related rows behind our back, so
  every query says what it loads (`selectinload`). A forgotten one fails in tests. It
  caught a real bug while building this stage.

## Consequences
- New enums `WorkoutStatus`, `WorkoutPart`, `PlanEndReason`; migration "create plan tables".
- `build_block(..., block_number=, recovery_week=)`; `Picker(..., block_number)`;
  `as_test_workout()` moves a skipped test using the same marking rules as building it.
- The preview command gains `--block 2` and `--recovery-week`.
- Next stage: sessions (start, log sets, finish with feedback) set `done`, then
  progression changes the saved numbers.

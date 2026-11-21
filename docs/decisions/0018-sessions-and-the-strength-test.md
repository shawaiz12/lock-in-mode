# 0018 – Sessions: doing a workout, logging sets, and the strength test

**Date:** 2026-11-21
**Status:** Accepted

## Context
Plans are saved and served as a queue (ADR 0017), but nothing can be done with them yet:
no workout can be started, no set logged, nothing marked done. The brief asks for
one-tap logging pre-filled from the plan (3.4), feedback after every workout (3.2), and
"missed days never pile up". ADR 0012 made the first workout a strength test; this ADR
makes its results count.

## Decisions

### 1. One tap per set, pre-filled (user's choice)
Each set shows its target; the user taps ✓, or changes the number first.
`PUT /sessions/{id}/sets/{planned_exercise_id}/{set_number}` with `reps` and/or `seconds`,
plus `weight_kg` for weighted moves.
- **PUT, because ticking the same set twice is safe**: the second replaces the first
  (fixing a typo, or a retry after a dropped connection). It's an upsert on
  (session, exercise, set number). `DELETE` on the same path unticks a mis-tap.
- **Pre-fill:** every planned exercise now carries `last`, the most recent set logged for
  that exercise in any workout ("last time: 20 kg × 10"). One query (`DISTINCT ON`).
  This is also how a gym user's starting weight carries forward (decision 3).
- ✅ Real numbers, so "your push-ups went 8 → 14" and progression (next stage) can work.
- ❌ "One tap for the whole workout" was rejected: people tap it without checking, so the
  data stops being honest. ❌ "No set logging" was rejected: nothing to progress from.

### 2. Stopping halfway: continue later, and half counts (user's choice)
- `POST /sessions {workout_id}` starts the next workout: 201. Calling it again for the
  same workout continues the open session: 200, same session. `GET /sessions/current` lets
  the app offer "Continue" or "Finish now" on launch.
- `POST /sessions/{id}/finish` works at any point, early or not: the workout is **done**
  and the queue moves on (no shame, brief principle 4).
- Starting a different workout while one is open finishes the open one first, with what
  was logged. Changing the answers mid-workout does the same before the plan is replaced,
  so nothing logged is ever lost.
- A started workout can't be **skipped** (409 `session_in_progress`): half a workout
  counts, so the app offers "Finish now" instead.
- The database guarantees **one open session per user** (partial unique index, like one
  current plan) and **one session per planned workout**.

### 3. The strength test changes the plan right away (user's choice)
When the test workout is finished, each **open test set** (bodyweight: "as many as you
can, stop with 2 left") places the user on that movement's ladder, KB section 2:

| Test | Result | Starts on |
|---|---|---|
| Push-ups | 0 · 1–4 · 5–14 · 15–29 · 30+ | incline · knee · push-up · decline · archer |
| Bodyweight squats | under 10 · 10–24 · 25+ | chair squat · bodyweight squat · one-and-a-half squat |
| Plank | under 20 s · 20–59 s · 60 s+ | knee plank · plank · plank shoulder taps |
| Pull-ups | 0 · 1–5 · 6+ | negatives · chin-up · pull-up |

Two small changes from the KB table: 0 push-ups starts on the incline push-up (the KB
groups 0–4 as "incline or knee"), and 25+ squats go to the one-and-a-half squat, because
the KB's tempo squat is the same difficulty as a bodyweight squat in our library.

- A placement is a **rung**: a difficulty (1–5) per movement, saved in `movement_rungs`.
  At home, the picker matches that movement's bodyweight moves to the rung instead of the
  level's cap, in both directions: a beginner who does 20 push-ups gets decline push-ups;
  someone with 0 gets incline push-ups whatever their level.
- **The rest of the block is rebuilt at once**: the generator is deterministic, so
  building the block again with the same answers, block number and the new rungs changes
  only the affected slots. Done and skipped workouts stay as they were. Every later block
  uses the rungs too.
- **Gym users aren't given rungs.** Their test is "pick a weight you can lift with 3 left"
  (KB section 2); the weight they log becomes `last` and pre-fills the next time. Rungs
  are ignored in the gym even if left over from training at home.
- A test move with no logged set places nothing; the level's default stays.
- The finish response lists the `placements` ("3 push-ups → knee push-up"), so the app can
  say what changed and why, honestly.
- ❌ "From the next block" was rejected: someone who did 0 push-ups would keep getting
  push-ups for 5 weeks.

### 4. Feedback: asked every time, can be skipped (user's choice)
`finish` takes an optional `feedback`: `too_easy`, `just_right` or `too_hard`. Skipped is
stored as NULL and **never treated as "just right"**, so progression (next stage) only
acts on real answers. A CHECK keeps feedback on finished sessions only.

## Consequences
- New tables `workout_sessions`, `set_logs`, `movement_rungs`; enum `Feedback`.
- `Picker(..., rungs=)`, `build_block(..., rungs=)`, `training/placement.py`.
- Planned exercises in API responses now have an `id` (to log against) and `last`.
- `plans.rebuild_pending()` reuses the generator to update the rest of a block; progression
  (next stage) can use the same path when it changes rungs or numbers.
- New error codes: `session_not_found` (404), `session_finished` (409),
  `session_in_progress` (409).
- Next: progression (KB section 10) reads the logged sets and feedback.

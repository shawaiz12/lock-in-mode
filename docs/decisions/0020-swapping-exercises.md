# 0020 – Swapping exercises: "this hurts, swap it"

**Date:** 2026-11-21
**Status:** Accepted

## Context
KB section 11: muscle effort and mild burn are normal; joint pain, or pain still there the
next day, is the signal to swap the exercise. "Every exercise has a one-tap 'this hurts,
swap it' that picks the same slot from the safe list and remembers the choice." The brief
(3.2) asks for easier, harder and equipment alternatives. Until now the only way out of a
painful move was to skip it, and the plan would pick it again next time.

## Decisions

### 1. "This hurts" swaps it out for good, with an undo (user's choice)
`POST /workouts/{id}/exercises/{planned_exercise_id}/swap` with `reason: hurts` saves the
exercise in `swapped_out_exercises` (one row per user and exercise). The Picker treats it
like a caution: **never offered again**, in this block or any later one, until the user
brings it back (`DELETE /me/swapped-out/{exercise_id}`). `GET /me/swapped-out` lists them
for an "Exercises you swapped out" screen with "bring it back".
- Today's row gets the stand-in at once; **the rest of the block is rebuilt** without the
  exercise (ADR 0018's path). Bringing it back rebuilds again, and because the generator
  is deterministic, the rest of the block goes back to what it was (today's workout keeps
  its stand-in).
- Progress on the swapped-out exercise (ADR 0019) is kept, in case it comes back.
- ❌ "Only this workout" was rejected: pain usually comes back with the same move, so the
  user would tap again every time. ❌ "Until the block ends" was rejected: it would
  return without warning.

### 2. The app picks the stand-in; "show another" is for today only (user's choices)
The stand-in comes from the same safe list as the plan (kit they own, no caution, nothing
swapped out) and does **the same job**:
- the same movement slot (a squat for a squat; a warm-up move for a warm-up move),
- the same kind of target (holds for holds, reps for reps), so the numbers still fit,
- **never more impact** (no jumping where there was none),
- not already in this workout.

For "this hurts", **same or easier comes first** (it just hurt), then right for their level
or rung, then the same main muscle, then the closest difficulty. The row keeps the slot's
sets, reps and rest.

`reason: another` ("show another") swaps today's row only: later workouts are unchanged and
nothing is remembered. Tapping again walks through the options in a fixed order (the
plan's own preference), so it never bounces between two. The user chose "today only" over
the recommendation (also remembering passed-on picks): the passed-on exercise didn't hurt,
so there is no safety reason to keep it away, and if it does hurt, "this hurts" removes it.
- ❌ "Choose from a list" was rejected: an extra decision mid-workout, and beginners don't
  know which to pick. ❌ "No choice" was rejected: stuck if the stand-in doesn't suit them.

### 3. "Where does it hurt?" is optional and may suggest a limit (user's choice)
After a "this hurts" swap the app may ask once: knees, back, shoulders or somewhere else
(`PATCH /me/swapped-out/{exercise_id}`). Knees, back or shoulders that aren't already a
limit come back as `suggest_limit`. The app offers "Go easy on your knees in every
workout?" **after the workout**, because changing the profile finishes an open workout and
rebuilds the plan (ADR 0017, 0018). Yes = the existing `PUT /me/profile` with that limit
added. Skipping the question is fine; nothing else depends on it.
- ❌ "Always ask" was rejected: an extra screen on a one-tap action, mid-workout.
  ❌ "Never ask" was rejected: a sore knee would find the next painful move one at a time.

### 4. Nothing safe left: leave the slot out, and say so (user's choice)
If no stand-in fits, the row is removed from today's workout and the response says
`left_out: true`, so the app can say "Nothing else safe for this one, so we've left it
out." The rebuilt block can't pick the exercise either. "Show
another" with nothing else answers 409 `no_other_exercise` and changes nothing.
- ❌ "A gentle stretch instead" and ❌ "keep it with a warning" were rejected: never push a
  move, or an area, that just hurt.

### 5. Mid-workout: the stand-in asks only for the sets left (user's choice)
Sets already logged stay with the old exercise, so history and "last time" stay honest.
That row is marked `swapped_out` (shown done/greyed, its sets cut to the ones logged), and a
new row right after it holds the stand-in with the sets that were left. Later rows move
down one place. Rows swapped out mid-workout don't progress (ADR 0019).

### 6. Every exercise has the button (user's choice)
Warm-up, main, finisher, cool-down and HIIT moves can all be swapped: a jumping jack can hurt
a bad knee as much as a lunge. A strength-test move that is swapped stops being a test (the
count wouldn't place anyone on that ladder) and gets an ordinary target (8–12 reps, or 30 s).

### 7. Safety rails
- Only the **next** workout can be swapped (409 `not_next_workout` otherwise): later ones
  follow the plan and its rebuilds.
- A double tap can't swap out the stand-in by mistake: the request carries the
  `exercise_id` on screen, and if the row holds a different one, nothing changes
  (409 `exercise_changed`).
- **A started workout is never rebuilt** (by a swap, bringing one back, progression or a
  placement): its logged sets point at its rows.

## Consequences
- New table `swapped_out_exercises`; new column `planned_exercises.swapped_out`; enums
  `SwapReason`, `BodyArea`. One migration.
- `Picker(..., excluded=)` and `build_block(..., excluded=)`; pure stand-in rules in
  `training/swaps.py`; `services/swaps.py`; routes in `api/v1/swaps.py`.
- `rebuild_pending(..., keep=)` skips today's workout and every started one.
- New error codes `exercise_changed` (409) and `no_other_exercise` (409).
- Planned exercises in responses have `swapped_out`.
- Not covered: a free choice from the whole library ("I want this exercise instead"), and
  swaps of workouts further down the queue.

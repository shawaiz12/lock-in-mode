# 0019 – Progression: targets that move with the user

**Date:** 2026-11-21
**Status:** Accepted

## Context
Workouts can be done and logged (ADR 0018), but every target stays where the plan put it:
someone who does 12, 12, 12 gets the same 8–12 again for five weeks. The brief (3.2) asks
the plan to adapt: "too easy" or hitting the target reps should mean more reps, rounds,
weight or a harder variant, and feedback is the main personalisation signal. KB section 10
holds the rules. The data is there: `set_logs` (reps, weight, seconds per set),
`workout_sessions.feedback`, `movement_rungs`, and `last` per exercise.

## Decisions

### 1. Progress is its own table, applied when a workout is served (user's choice)
`exercise_targets` has one row per user and exercise: suggested `weight_kg`, `set_change`
(-1, 0 or +1 sets compared with the plan), `seconds` (holds), `reps_bonus` (a one-off
nudge) and `short_runs` (see 4). No row = the plan's numbers as they are; a row is written
only when something actually changes.
- **The saved plan stays the starting point.** `GET /workouts/{id}` and `/plans/current/next`
  add the progress to *pending* workouts; done and skipped workouts show what was saved,
  so history stays honest.
- ✅ **Rotation works for free:** the barbell bench in Push A and again in Push C share one
  row. ✅ **Survives rebuilds:** a rebuilt block (new rung, changed answers) keeps it.
  ✅ **Next block "picks up where you left off" (user's choice):** the rows simply stay.
  The recovery week was the break, so there's no step back between blocks, and nobody
  feels they lost progress (brief principle 4). This replaces the KB's "next block starts
  one notch above the last one's start".
- Each planned exercise now has `weight_kg`: the suggested weight, else the last weight
  logged, else null.
- ❌ "Edit the saved plan" was rejected: a rebuild would wipe progress, and the original
  plan would be lost. ❌ "Harder moves only" was rejected: weights and the gym got nothing.

### 2. Double progression: the top of the range on every set, once (user's choice)
All the sets asked for, each at the top of the rep range (holds: the full time), in one
workout → one step up next time, and the reps start again from the bottom.

| Kind | One step up |
|---|---|
| Weights | Heavier by one step (decision 3). If they stayed lighter than suggested and still hit the top, an extra set instead: home dumbbells may not go heavier. |
| Bodyweight | One extra set, then **the harder move right away** (user's choice) |
| Holds | +5 s up to 60 s, then the harder move |

- **The harder move** (home only) moves the movement's rung one step up the user's ladder
  (the nearest difficulty they can do), saved in `movement_rungs` like a test placement,
  and the rest of the block is rebuilt (ADR 0018's path). A new move starts from the plan's
  numbers. The step-back rule (4) catches a jump that's too big.
- **In the gym**, bodyweight moves stop at the extra set: rungs don't apply there (ADR 0018).
- **Circuits** share their rounds, so they skip the extra set.
- ❌ "Twice in a row" was rejected: with rotation it can take two weeks to move up.
  ❌ A slow-lowering (3 s) step from the KB was left out: harder to explain in a one-tap
  app, and the squat ladder already has a tempo rung.

### 3. Weight steps are fixed jumps by equipment (user's choice)
Dumbbells: the next pair (+2.5 kg). Barbells: +2.5 kg upper body, +5 kg legs and hips.
Machines and cables: the next pin (+5 kg). Kettlebells: +4 kg. The user can always type
the weight they really used; the lightest weight logged is the base, to be safe.
- ❌ Percentages were rejected: on a 6 kg lateral raise, rounding makes them jump oddly.

### 4. The feedback tap, and falling short
- **Once:** "too easy" → aim 2 reps higher next time (holds +5 s). "Too hard" → no step up
  even at the top: repeat the same targets.
- **Twice in a row, any workouts (user's choice):** every exercise done so far that is still
  in the block moves one notch, up or back. Skipped taps are no answer (ADR 0018), so they
  don't break or make a pair; "just right" breaks it. A third "too easy" is a single nudge
  again; the 4th makes a pair. Recovery weeks don't count.
- **Falling short:** the first set 3+ reps under the bottom of the range (holds 10 s short)
  in two workouts of that exercise in a row → that exercise steps back one notch.
- **One notch back** (KB: -1 set, -1 rung or about 10% lighter): an extra set goes first;
  then weights about 10% lighter (at least one step), holds -10 s (not under 10 s),
  bodyweight one rung down; last resort one set fewer, never below one set.

### 5. Sets stay flat within a block (user's choice)
The KB's "+1 set per muscle every week" is left out. Progress comes from reps, weight and
harder moves, so workouts keep fitting the minutes the user chose. An earned extra set adds
about 1.5–2 minutes and is capped at one per exercise.

### 6. The recovery week can come early, as earned recovery (user's choice)
"Too hard" on more than half of a build-up week's workouts (2 of 3, 3 of 4) → the rest of the
build-up weeks get status `replaced_by_recovery` and the recovery week is next. The finish
response says `recovery_earned: true`, so the app shows it as earned recovery (with full
XP once gamification exists), never as failing.
- ❌ "Only step exercises back" was rejected: a worn-out user would keep going without a
  real break.

### 7. The recovery week changes nothing
Its sessions don't step anything or count toward a pair. It keeps its lighter numbers and
only takes the suggested weight ("same weight, stop 4 reps short").

## Consequences
- New table `exercise_targets` (5 CHECKs); new `WorkoutStatus.REPLACED_BY_RECOVERY`;
  new enum `ProgressChange`.
- Pure rules in `training/progression.py`; `services/progress.py` runs them when a workout
  is finished, in the same transaction. Finishing now: progression and the test placement,
  one rebuild if a rung moved, then the early recovery check.
- `POST /sessions/{id}/finish` also returns `progress` (what changed per exercise) and
  `recovery_earned`. Planned exercises have `weight_kg`.
- Not covered yet: cardio and HIIT progression (KB section 7), "this hurts, swap it",
  coming back after a break, and moving up a level. Those come next.

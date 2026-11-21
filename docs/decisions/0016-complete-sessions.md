# 0016 – Plan generator stage 2b: complete sessions

**Date:** 2026-11-21
**Status:** Accepted

## Context
After stage 2a (ADR 0015) every strength session has a main block, but a real workout
also needs a warm-up and a cool-down. Cardio, HIIT and mobility days were empty, the
fat-loss finisher was only a flag, and the first-workout strength test (ADR 0012,
decision 4) wasn't built. Stage 2b completes every session and fits the **whole** thing
(not just the main block) into the user's minutes.

## Decisions

### 1. The minutes are split as the KB says (section 9)
| Session | Warm-up | Main | Cool-down |
|---|---|---|---|
| 10 | 2 | 7 | 1 |
| 20 | 3 | 15 | 2 |
| 30 | 4 | 23 | 3 |
| 45 | 5 | 36 | 4 |
| 60 | 5 | 50 | 5 |
| 75 | 6 | 63 | 6 |
| 90 | 7 | 76 | 7 |
| No limit | 5 | unlimited | 5 |

A finisher comes **out of** the main block (4 min at 20, 5 at 30, 6 at 45, 8 at 60+), so
the strength part shrinks to make room. A 10-minute session has no room, so stage 1 no
longer promises a finisher there.

### 2. Warm-up and cool-down (KB section 8)
- **Warm-up:** raise the pulse (march in place or step jacks, 60–120 s), then 1–2 joint
  moves for the day (upper: arm circles, cat-cow; lower: leg swings, hip circles; full
  body: world's greatest stretch). Then **1–2 light practice sets** of the first lift
  (2 for weights, 1 for bodyweight) when the warm-up has room. None in 10-minute sessions,
  none for holds or test sets.
- **Cool-down:** an easy walk (30–60 s), then 1–4 stretches of 30 s for the muscles that
  were trained, and only those. Shoulders and arms map to the chest and back stretches.
- **Easy walks and mobility days get neither**: they're gentle already.

### 3. HIIT (KB section 7)
- One move from each area, so nothing gives out early: lower body, cardio, push, core,
  full body. Rotated through 3 options per area, like strength picks.
- Work / rest by level: beginner 20/40, some experience 30/30, experienced 40/20, with
  effort 7, 8 and 9 out of 10 (the talk test).
- Rounds fill the level's block (10, 16, 20 minutes) or the main block if shorter.
- **Impact by level:** beginners low impact only, some experience up to medium,
  experienced anything. All on top of the cautions (knees, low intensity, quiet track).

### 4. Steady, long and easy cardio, and mobility
- One continuous activity at talking pace, filling the main block (no limit: 30, 45 or 20
  minutes for steady, long and easy). Walking comes first because everyone can do it
  anywhere. Gym users rotate through the machines.
- Mobility: a flow of joint moves and stretches, 40 s each, 12 minutes at most.

### 5. Finishers
Two moves taking turns in the level's intervals, low impact for beginners. Example 1 in
the KB (4 rounds of 20 s on, 40 s off) comes out exactly.

### 6. The first-workout test (KB section 2)
Only the **first strength workout of the user's first block** (`build_block(...,
first_block=True)`). Each test movement is tested once:
- **Bodyweight:** the standard move (push-up, bodyweight squat, plank, pull-up) with an
  **open target**: "as many as you can with good form, stop with 2 left". The KB's ability
  table turns the result into a starting rung. The standard move is swapped in only if
  it's safe for the user and not already in the workout.
- **Weights:** the lift keeps its reps and asks for "a weight you can lift with 3 left".

### 7. Named move lists are data, checked by a test
The KB names specific moves (march in place, world's greatest stretch, squat thrust…).
They live as slug lists in `training/conditioning.py`, always filtered through the
Picker (can do, no caution). A test fails if any slug is missing from the library, so
renaming an exercise can't silently empty a warm-up.

## Consequences
- The generator code is now split into modules: `plan_types.py` (shapes and numbers),
  `picker.py` (choosing with rotation), `conditioning.py` (warm-up, cool-down, finisher,
  cardio), `sessions.py` (strength sessions and putting each workout together).
- `Workout` now has `warm_up`, `finisher` (moves, not a flag), `cool_down` and
  `total_minutes`. `PlannedExercise` gains `effort`, `practice_sets` and `test`, and
  `reps_in_reserve` may be empty for cardio. New formats: `intervals`, `continuous`, `flow`.
- Sweep before shipping: 151,200 workouts (every goal × level × 5 setups × 2–6 days × 7
  lengths × low intensity × limits × quiet track, first block, 2 weeks). Every move is
  safe and possible, HIIT and finisher impact fits the level, nothing repeats, and every
  session fits its total minutes. It caught a double push-up when a push day's two chest
  slots both became the test.
- Next, stage 3: save blocks, the "next workout" queue and the plan endpoints.

# 0015 – Plan generator stage 2a: filling strength sessions

**Date:** 2026-11-21
**Status:** Accepted

## Context
Stage 1 (ADR 0014) decides *which* sessions a week has. Stage 2a fills every strength
session (full body, upper/lower, push pull legs, bro split, stamina circuits) with
exercises, sets, reps, rest and effort, fitted to the user's minutes, across a whole
training block, with the planned rotation from ADR 0014. Cardio, HIIT, mobility,
warm-ups, cool-downs and the first-workout test come in stage 2b.

## Decisions

### 1. Templates are lists of movement slots (KB section 5)
`training/templates.py` holds every template as data: full body A/B/C, upper A/B,
lower A/B, push and legs (both shoulder placements), pull, the five bro split days
(with their light second touch) and circuits A/B.
- A slot is a *job* ("horizontal push, upper chest"), not an exercise. One template
  serves home, bands and gym users.
- `prefer` asks for an emphasis (incline press → upper chest; biceps → long head), so
  push, pull and arm days cover every head of their muscles.
- `fallback`: no pull-up bar, bands or gym turns the vertical pull into a second row (KB).
  A slot nothing can fill (e.g. a gym-only isolation move at home) is skipped.

### 2. Picking: safe, possible, level-appropriate, then rotated
Candidates: the slot's exercises the user **can do** (equipment, location) and that carry
**no caution** (body limits, safety result, quiet track; ADR 0013). Ranked by:
1. within the level's starting difficulty (beginner ≤ 2, some experience ≤ 4,
   experienced ≤ 5). If nothing fits, the easiest that exists (e.g. pike push-up at home);
2. the slot's wanted emphasis, then a main muscle that matches it;
3. effectiveness (highest first), then difficulty (safer first), then name.

Rotation (ADR 0014): big lifts take turns between the top **2**, small moves between the
top **3**, on a fixed pattern. Nothing repeats inside one session. Example: Upper A gets
dumbbell bench press in week 1 and barbell bench press in week 2.

### 3. Numbers by goal and level (KB section 3)
| Goal | Reps | Rest | Reps left in the tank |
|---|---|---|---|
| Build muscle (weights) | 6–10 first lift, 8–12 other lifts, 10–15 small moves | 90 s / 60 s | 2 |
| Build muscle (bodyweight, bands) | 10–20 lifts, 15–25 small moves; **6–12 for hard moves** (difficulty 4+: pull-ups, pistols) | 90 s / 60 s | 2 |
| Build strength | 3–6 on the first two lifts (beginners 5–8), 8–12 the rest | 150 s / 75 s | 2 |
| Lose fat | 8–15 (bodyweight 10–20) | 60 s | 2 |
| Stamina | 12–20 | 30 s | 3 |
| Stay active | 8–12 | 60 s | 3 |

Sets: beginners, stay active, low intensity and light touches get 2. Lose fat and stamina:
3 on lifts, 2 on small moves. Strength: 4 and 3. Build muscle: 3 on lifts (4 on an
experienced user's first lift), small moves 2 (3 when experienced). Beginners always
stop 3 reps short; low intensity stops 4 short. Timed holds get 25/40/50 s by level.

### 4. Fitting the minutes (KB section 9)
- Format by session length: 10 min → circuit with no rest; 20 → supersets; 30 → first
  exercise on its own, then supersets; 45+ or no limit → straight sets. Stamina sessions
  are always circuits.
- Estimate: a set is about 40 s of work plus its rest; a superset pair is about 40% faster;
  a circuit adds 60 s between rounds.
- Over budget: drop slots, then cut sets (never below 2), then shorten rests to the
  goal's low end. **The three most important slots are never dropped.**
- **Drop priority is separate from exercise order.** Push day is done chest → shoulders →
  triceps (big muscle before helper), but when time is short it drops the fly and rear
  delt before the first triceps move. That's how the KB's own worked example 3 is built,
  and it keeps every muscle of the day trained.
- "(if time)" slots are added when they fit, and always with no time limit.

### 5. Tested against the real library
- The KB's five worked examples, rotation (2 and 3 picks), fallbacks, big-before-helper
  order, the optional slots and the hard-bodyweight rule.
- A sweep over many users (every goal × level × 5 equipment setups × days × minutes ×
  limits × low intensity, 2 weeks each): every pick is possible and caution-free, nothing
  repeats in a session, every session has at least 3 exercises, and none runs over its
  time. Before shipping, the same check ran on 239,200 workouts with no failures. It
  caught 10-minute stamina circuits running over (they had rest between exercises) and
  push day losing all its triceps.

## Consequences
- New enum `WorkoutFormat`. Stage 3 stores it.
- `build_block(answers, routine, library, weeks)` returns every workout of a block. The
  exercises are referenced by slug, and stage 3 maps slugs to ids when saving.
- The preview command now prints full workouts (`--weeks 2` shows the rotation).
- Stage 2b next: warm-up and cool-down, HIIT, steady and easy cardio, mobility sessions,
  finishers, and the first-workout test.

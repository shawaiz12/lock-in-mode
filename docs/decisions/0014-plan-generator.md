# 0014 – Plan generator: a queue, planned rotation, saved blocks

**Date:** 2026-11-21
**Status:** Accepted (stage 1 built; stages 2 and 3 follow this ADR)

## Context
The plan generator turns onboarding answers (ADR 0012) into workouts, following the
Training Knowledge Base (KB). It's the core of the product and the biggest piece of
logic in the backend, so it's built in three stages, each tested before the next:

1. **Routine:** which sessions make up the week, in what order, on which suggested days.
2. **Sessions:** the exercises, sets, reps and rest for each session, fitted to the
   user's minutes, with warm-up and cool-down.
3. **Saving and serving:** plan tables, `GET /plans/current`, the "next workout" queue.

## Decisions

### 1. A "next workout" queue, not fixed weekdays
The home screen always shows the **next** session ("Next: Full body B"). Users train
when they can. The plan suggests weekdays (shown on the plan screen), but nothing is
ever "missed" and nothing piles up.
- ✅ Fits the no-shame rule (brief 3.2): a missed Tuesday simply doesn't exist.
- ✅ No extra onboarding question about which weekdays.
- ❌ Fixed weekdays were rejected: one more question, and "you missed Monday" logic.
- Suggested days still follow every layout rule, so a user who follows them recovers
  well. The queue order is the layout order.

### 2. Exercises rotate on a fixed pattern
The user asked for rotation ("bench press one workout, dumbbell press the next") to keep
training fresh. Research supports *planned* variation and warns against *random*
variation: a 2022 systematic review (Kassiano et al., J Strength Cond Res) found that
some systematic variation helps muscle growth in different regions and strength, while
excessive random variation may cost gains. So:
- **Big lifts** (the first slots of a template) alternate between **2 picks**: Upper A
  gets barbell bench press, Upper B gets dumbbell press, then back to the bench.
- **Small moves** (isolation, core, second pulls) cycle through **3 picks**.
- **Each new block** (4 to 6 weeks) brings in fresh picks.
- Picks are **deterministic**: ranked by effectiveness for the user's level, never a
  move with a caution (ADR 0013), never one they can't do. The same answers always give
  the same plan, which makes it testable. Each move still comes back regularly, so
  "your dumbbell press went 20 → 24 kg" works.
- This replaces the KB's "keep the main exercise for a whole block" (section 10) with
  "keep the same 2 main exercises for a whole block".

### 3. Plans are saved, one per training block
The generated block is saved (brief section 5: `plans`, `planned_workouts`,
`planned_exercises`), with the rotation already applied.
- ✅ Progress, the lighter week and history need something stable to attach to.
- ✅ A change to the exercise library never silently changes a plan in progress.
- Changing the profile (e.g. 3 → 4 days) starts a new block. Progress lives on the
  exercises, not the plan, so it's kept.
- ❌ Recalculating on every request was rejected for the reasons above.

### 4. Stage 1 rules (KB section 4 and 7), and where we went past the KB
`training/routine.py` → `choose_routine(answers) -> Routine(kind, sessions, weekdays, reasons)`.
Pure: no database, no clock.
- Days × level table, goal changes (lose fat, stamina, stay active, strength), short
  sessions, push pull legs needing 30+ minutes and a way to pull, bro split only when
  available and chosen, low intensity (no HIIT, no finishers). All as in the KB.
- **Beginners: at most 3 hard sessions a week, HIIT and circuits included.** The KB caps
  strength days at 3, and beginners need an easy day after every hard day. 4 hard days
  can't each be followed by an easy one in 7 days, so 5–6 day lose-fat and stamina weeks
  for beginners keep 3 hard days and turn the rest into steady or easy cardio.
- **Short sessions (10/20 min) on 4–6 days:** full body only (KB), and full body can't go
  on back-to-back days, so it's 3 full-body sessions plus easy cardio.
- **Build strength never gets push pull legs.** The KB says "prefer full body or
  upper/lower" so main lifts come back 2–3 times a week. We made it a rule.
- **No push pull legs at home without pulling kit or under 30 minutes:** upper/lower
  instead (5 days: upper, lower, full body, upper, lower).
- **Rest days:** everyone gets at least 1 empty day. Beginners get at least 2 days
  without a hard session (easy cardio and mobility count as easy). This is how we read
  the KB's "2 rest days for beginners" next to its own 6-day beginner week.

### 5. Laying out the week: a small, exhaustive search
Rules: no muscle trained hard on back-to-back days, beginners go easy after every hard
day, no two HIIT days in a row, no HIIT the day before legs, at least one rest day.
Sunday runs into Monday, because the queue repeats.
- The search tries the KB's example weeks first (e.g. 3 days = Mon, Wed, Fri), then every
  other choice of days, then every other order of sessions: at most 720 × 35 checks,
  which takes microseconds.
- ✅ Brute force is easy to trust: there are no clever heuristics to get wrong.
- A test runs **all 21,600 combinations** of answers and checks every rule on the result
  with its own independent checker.

### 6. "Why" lines are part of the output
Every rule that changes the plan adds a plain-language reason ("Beginner: 3 hard
workouts a week at most…"). They power the honest "building your plan" screen
(docs/onboarding.md, screen 12). Finisher and HIIT lines are written **after** the
safety rules run, so the text never promises something the user won't get.

## Consequences
- New enums `RoutineKind`, `SessionKind`. Stage 3 stores them.
- `Routine.uses_push_pull_legs` tells the app when to ask the shoulder question.
- `python -m lock_in_mode_api.training.preview` prints any user's week and reasons.
- Stage 2 next: templates → slots → picks (with rotation), sets/reps/rest by goal and
  level, fitting the minutes, warm-up and cool-down, the first-workout test targets, and
  the KB's worked examples as tests.

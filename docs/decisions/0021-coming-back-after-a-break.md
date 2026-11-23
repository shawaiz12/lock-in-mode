# 0021 – Coming back after a break

**Date:** 2026-11-23
**Status:** Accepted

## Context
KB section 10 says what to do when someone stops training and comes back:

| Time away | Restart at |
|---|---|
| Under 1 week | Where they left off |
| 1 to 2 weeks | Repeat the last completed week |
| 2 to 4 weeks | 20% fewer sets and 10 to 20% lighter, back to normal in 1 week |
| Over 4 weeks | Half the sets, one rung easier or 30 to 40% lighter, rebuilt over 2 to 3 weeks |

ADR 0012 dropped the "coming back after 6+ months off?" onboarding question and left this
table for users who stop *using the app*. Until now the plan didn't notice a break: after
two months away, the next workout asked for the same weights as the day they left. The
brief's principles apply: missed days never wipe progress (4), and the plan stays safe (5).

Since ADR 0017 the plan is a queue, not set weekdays, and since ADR 0019 sets stay flat
within a block, so every build-up week of a block asks for the same work.

## Decisions

### 1. Time away = days since the last workout they trained in (user's choice)
The clock starts at the **last set they ticked**, in any workout (a half-finished one
counts, ADR 0018; so does one left open). Opening the app, pressing Skip, or starting a
workout and ticking nothing doesn't reset it: none of them keeps you fit. Whole days.
Someone who has never trained in the app has no break: workout 1 is the strength test.
- ❌ "Since the app was last opened" was rejected: someone who opens it daily without
  training would never be eased back in. ❌ "Since a workout was last started" was
  rejected: one set and quitting would reset it.

### 2. Three bands (user's choice)
| Days away | What happens |
|---|---|
| Under 14 | Carry on: nothing changes |
| 14 to 28 | **1 easy week** |
| Over 28 | **3-week ramp** back up |

The KB's "1 to 2 weeks: repeat the last completed week" joins "carry on": our build-up
weeks are already the same, so repeating one changes nothing (ADR 0019).
- ❌ "The KB's four bands as written" was rejected: the extra rule (no step-ups on the first
  workout back) is a small difference for one more rule. ❌ "Two bands (3 weeks)" was
  rejected: too little care after long breaks.

### 3. Saved progress is kept; an easier layer fades out (user's choice)
Exercise targets, weights and rungs (ADR 0018, 0019) are **not touched**. Comeback workouts
are served lighter, the way the recovery week is, and the layer is gone once the comeback
is over. If the saved numbers turn out too hard after that, the normal step-back rule
(3+ reps short twice) and the "too hard" tap still catch it.

How each comeback week is eased (applied to the served numbers: plan + progress):

| | Sets (min 1) | Weights | Bodyweight reps | Holds |
|---|---|---|---|---|
| Easy week (14–28 days) | 80% | 85% | as usual | as usual |
| Ramp week 1 (over 28) | 50% | 65% | bottom of the range | 10 s shorter |
| Ramp week 2 | 75% | 80% | bottom of the range | 5 s shorter |
| Ramp week 3 | 100% | 90% | as usual | as usual |

- Sets round to the nearest whole set (halves round up), never below 1: 3 sets → 2 in the
  easy week, 2 in ramp week 1, 2 in ramp week 2. Circuits ease their shared rounds the same
  way, so every exercise keeps the same number of rounds.
- Weights round **down** to the exercise's weight step (ADR 0019's fixed jumps), never
  below one step. No suggested weight yet = nothing to ease; the "last time" pre-fill is
  eased the same way.
- Holds never go under 10 s.
- Intervals and finishers: 2 points easier on the talk test (as in the recovery week,
  never under 3) in every eased week except ramp week 3. Warm-ups and cool-downs are
  unchanged.
- **Home bodyweight keeps the same move (user's choice).** The KB's "one rung easier" would
  mean rebuilding the block twice (easier moves in, then back out a week later) and quietly
  saving the comeback as soon as the app opens. Half the sets, aiming at the bottom of the
  range, already halves the work.
- ❌ "Lower the saved numbers and earn them back" was rejected: it feels like losing
  progress (principle 4) and can take weeks of double progression. ❌ "Lower only after 4+
  weeks" was rejected: two rules for one idea.

### 4. Automatic, with an opt-out (user's choice)
No question is asked. The next workout is already eased when the app shows it, with a
"Welcome back" note (never guilt: no "you missed 5 weeks"). A button, **"I kept training
elsewhere"**, ends the comeback for every workout not yet started (`DELETE /me/comeback`);
a workout already started keeps the numbers it started with. Opting out before the first
comeback workout also keeps the recovery week (decision 7): they say they didn't rest.
- ❌ "Ask first" was rejected: an extra screen on a low-motivation day (Retention
  knowledge, Source 1: the lazy thumb and the paved path). ❌ "No opt-out" was rejected:
  someone who trained at another gym while travelling would get a week or more too easy.

### 5. A comeback week = the user's workouts per week (user's choice)
An easy week is as many workouts as they train per week (2–6, the answer saved when the
comeback starts); the ramp is three times that. The ease-in is counted in **workouts
trained**, not calendar days: skipped workouts don't count, so someone who comes back
once and vanishes again still has their ease-in waiting.
- ❌ "Calendar days" was rejected: the ease-in could run out without a single workout.

### 6. Comeback workouts change nothing (user's choice)
Like the recovery week (ADR 0019): no step-ups, no step-backs, and their feedback taps
neither make nor break a "same tap twice" pair, nor count toward earned recovery. Hitting
the top reps on a lighter weight says nothing about the saved weight, and struggling while
rusty says nothing about the saved one either.
- A strength test still waiting (ADR 0017) runs as usual and is **not eased**: its open
  targets are already self-paced ("stop with 2 left"), and it measures where they are now.
  Its placement still counts.
- ❌ "Only step-backs count" was rejected: it punishes ordinary rust. ❌ "Count everything"
  was rejected: targets would climb from lighter weights and then feel too heavy.

### 7. The break replaces a waiting recovery week (user's choice)
If the comeback starts (14+ days away) while the queue's next workouts are the recovery
week, those workouts get the new status `replaced_by_break`: the break was the rest. The
ease-in starts on the next build-up workout, or on the next block if none is left. Not a
skip, never shown as missed. This mirrors ADR 0019 ("the recovery week was the break").
- ❌ "Use the recovery week as the ease-in" was rejected: too short after long breaks.
  ❌ "Keep both" was rejected: two to four easy weeks in a row feels like going nowhere.

### 8. Rules around it
- **Nothing is saved until they train.** While a comeback is only due, the API works it
  out on each read (no writes on GET). Starting the next workout (`POST /sessions`) saves
  it, links that session to it, and drops a waiting recovery week. Starting the next
  block (`POST /plans`) with only a recovery week left does the same drop first.
- **One open comeback per user.** It belongs to the user, not the block: a ramp carries on
  into the next block, and a profile change (new plan, ADR 0017) doesn't end it.
- **It ends** when its workouts are trained (`done`), on "I kept training elsewhere"
  (`opted_out`), or when a new break of 14+ days starts a new one (`new_break`).
- **A new break during a comeback** starts a new comeback sized by the new break.
- **Which break a comeback covers** is saved with it (`trained_until`: the last ticked set
  before the break, as the database stamped it). A break is new when a set was ticked
  after that. Comparing the database's time with itself means a few seconds of difference
  between the app server's clock and the database's can't hide a break.
- **Opting out of a due comeback** saves it already ended, so the same break isn't found
  again; the next one counts from their next trained workout.
- **A recovery week that comes during the ease-in** (they came back with build-up workouts
  left, decision 7) stays the recovery week: it isn't eased again and doesn't count. The
  ease-in carries on after it, into the next block.
- **A workout left open since before the break** is the next workout, so "Continue" on it
  starts the comeback: its sets left are eased, the sets already ticked stay.

## Consequences
- New table `comebacks`: user, the break it covers (`trained_until`), days away (14+),
  weeks (1 or 3), workouts per week (2–6), started_at, ended_at and end reason (both set
  or both empty), one open per user (partial unique index).
- `workout_sessions` gets `comeback_id` and `comeback_week` (both set or both empty, week
  1–3): a started workout keeps its eased numbers, and the count of trained comeback
  workouts comes from them. Those two CHECKs are on an existing table, so autogenerate
  misses them: they're written by hand in the migration.
- New `WorkoutStatus.REPLACED_BY_BREAK` (stored as text: no migration for the value).
- Pure rules in `training/comeback.py` (band from days away, which week a workout falls
  in, the easing table); `services/comeback.py` finds a due or open comeback and starts
  and ends it (it reads models only, so the plans service can use it). `plans.queue_of`
  works out the queue as the user sees it (next workout, comeback week per workout,
  whether the recovery week is dropped); serving, skipping, swapping, starting a workout
  and starting a block all go through it.
- API: `PlanRead.comeback` (days away, weeks, current week, workouts left, started) and
  `WorkoutSummary.comeback_week`; pending workouts are served eased; `DELETE /me/comeback`
  (204; 404 `not_found` when there's no break to come back from).
- Later: "comeback quests" and welcome-back XP belong to gamification (brief 3.5, phase 4).
  Still open from KB section 10: moving up a level ("ready for more?"). Still open from
  KB section 7: cardio and HIIT progression.

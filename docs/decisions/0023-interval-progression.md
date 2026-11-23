# 0023 – Interval progression: HIIT and finishers get harder as you do

**Date:** 2026-11-23
**Status:** Accepted

## Context
Strength work moves with the user (ADR 0019), but HIIT sessions and finishers don't. They
are built from the level's fixed settings (KB section 7, `training/conditioning.py`):

| Level | Work / rest | Work block | Effort |
|---|---|---|---|
| Beginner | 20 s / 40 s | 10 min | 7 |
| Some experience | 30 s / 30 s | 16 min | 8 |
| Experienced | 40 s / 20 s | 20 min | 9 |

So a user does the same `30 s on / 30 s off × 3 rounds` in every HIIT workout of every
block. Only a level change (ADR 0022) changes that.

KB section 7: "Progress HIIT in this order: add a round, lengthen the work time, shorten
the rest, then move to harder moves." Reading the code showed which of these fit:
- **Add a round** doesn't fit. A HIIT round is one turn through 4 to 6 moves, and the
  number of rounds already fills the level's work block (and the session's minutes).
  Another round would make the workout longer than the user said they have.
- **Harder moves** are already picked first: the HIIT picker ranks the hardest move the
  level's impact rules allow at the top (`_intensity_rank`).
- **Longer work and shorter rest** fit. Every level's interval is one minute (20+40,
  30+30, 40+20). If work goes up 5 s and rest goes down 5 s, the minute stays a minute.
  The workout gets harder and is never longer, and the finisher keeps its round count.

What the app already knows: every round of every move is a ticked set (one tap per set,
ADR 0018), so it can tell if all the rounds were done. It also gets the after-workout tap
(too easy / just right / too hard). HIIT moves rotate between workouts (ADR 0014), so
progress can't be kept per exercise like `exercise_targets`. It has to be kept **per
user**.

## Decisions

### 1. One step scale; each level climbs to the next level's timing (user's choice)
Five steps, each still one minute:

| Step | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| Work / rest | 20 / 40 | 25 / 35 | 30 / 30 | 35 / 25 | 40 / 20 |

| Level | Starts at | Climbs to | Can drop to (decision 5) |
|---|---|---|---|
| Beginner | 0 (20/40) | 2 (30/30) | 0 (20/40) |
| Some experience | 2 (30/30) | 4 (40/20) | 1 (25/35) |
| Experienced | 4 (40/20) | 4 (40/20) | 3 (35/25) |

The top of each level is the next level's start: a beginner at the top already does the
some-experience timing. Experienced users start at the KB's top and stay there (Tabata
20/10 is not part of this). Everything else stays as the level says: which moves are
allowed (beginners: low impact only), the effort number, the rounds.
- ❌ "Half a step past own level" was rejected: about one step a block, too little to feel.
  ❌ "Everyone up to 40/20" was rejected: the KB keeps 40/20 for experienced users, and
  too much HIIT is the fastest way to burn out a beginner (KB section 7).

### 2. Two good workouts in a row = one step up (user's choice)
Only workouts **with intervals** count (a HIIT workout, or a strength workout with a
finisher):
- **Good** = every interval round ticked, and the tap was not "too hard".
- **Short** = some rounds ticked but not all, or the tap was "too hard". What they did
  wins over the tap: short + "too easy" is short (as in ADR 0019). Rounds are counted per
  move: an extra round of one move (the API takes up to 20 sets) doesn't make up for a
  round missed on another.
- **Two good in a row** → one step up. **Two short in a row** → one step down. A good
  workout clears the short count and a short one clears the good count.
- **A feedback pair** (the same tap twice in a row, ADR 0019) moves the step too, like it
  moves every exercise: "too easy" twice → one step up, "too hard" twice → one step down.
  It never moves the step twice in one workout, and rounds missed win over a "too easy"
  pair. As in ADR 0019 ("never done: nothing to step from"), a pair only moves the step
  of a user who has done intervals before and whose current block has intervals (so a
  user who switched to a plan without them is never told "Intervals up").

With 2 HIIT days a week, that's about one step a week.
- ❌ "Every good workout" was rejected: a beginner would reach the top in 2 HIIT workouts.
  ❌ "Feedback taps only" was rejected: most users skip the tap, so most would never move.

### 3. HIIT and finishers share the step; steady cardio stays as it is (user's choice)
One step per user, used by HIIT workouts and finishers alike, and moved by both. A
beginner whose plan has finishers but no HIIT days moves up too. Steady, long and easy
cardio and mobility don't change: their length is the session's minutes (or 20 / 30 / 45
minutes with no limit), and the talk test makes the pace faster as the user gets fitter.
Low-intensity users have no HIIT and no finishers (ADR 0016), so nothing changes for them.
- ❌ "HIIT and finishers separate" was rejected: twice the rules and tests for the same
  kind of work. ❌ "Also lengthen steady cardio" was rejected: it only helps "no limit"
  users and pushes their sessions longer than they planned.

### 4. Recovery weeks, coming back after a break, level changes (user's choice)
- **Recovery week:** the user's step, with the recovery week's half rounds and effort −2,
  as today. Recovery workouts change nothing (ADR 0019).
- **Coming back after a break (ADR 0021):** in the comeback weeks that already ease effort
  (the easy week, and ramp weeks 1 and 2), intervals are served **one step easier** (never
  below 20/40). The saved step is untouched, so the user is back on it after the comeback.
  Comeback workouts change nothing (ADR 0021).
- **Level change** (a level-up, ADR 0022, or a new level in the profile): the step moves to
  the new level's start. A beginner at 20/40 or 25/35 who moves up goes to 30/30. A beginner
  at 30/30 stays there.
- ❌ "Comeback = the level's start" was rejected: a bigger drop than strength gets.
  ❌ "Comeback = effort −2 only" was rejected: the timing would be as hard as before the
  break.

### 5. The floor is one step below the level's start (user's choice)
Beginners can't go below 20/40, the KB's gentlest timing. Some-experience users can drop to
25/35 and experienced users to 35/25, so every level has somewhere to go down to. Below the
floor, "too hard" keeps doing what it does today: it brings the recovery week forward as
earned recovery (ADR 0019).
- ❌ "Down to 20/40 for everyone" was rejected: an experienced user would end up far from
  their level. ❌ "Never below the level's start" was rejected: experienced users start at
  the top, so they could never step down.

### 6. A finisher left out entirely counts as nothing (user's choice)
If a strength workout is finished with **no** finisher rounds ticked (time ran out), the
workout doesn't count for the step: it is neither good nor short. The same goes for a
HIIT workout closed with no round ticked (for example, finished automatically because
another workout was started): there's nothing to judge. Some rounds ticked but
not all is short (decision 2). Half a workout still counts for strength (ADR 0018), and
skipping a finisher because of time shouldn't push intervals down.
- ❌ "Counts as short" was rejected: it would step down people who are short on time,
  not people who are struggling.

### 7. Shown on the finish screen and in the workouts (user's choice)
The finish result (`SessionResult.intervals`) says what moved: "Intervals up: 35 s on /
25 s off next time" (or down). Upcoming HIIT workouts and finishers simply show the new
timing. No extra screen and no reset endpoint: a "too hard" pair already steps it down.
- ❌ "Also a reset button" was rejected: more to build and test for something the taps
  already do.

### 8. Rules around it
- **Stored per user:** a new table `interval_steps` (one row per user: the step, the level
  it belongs to, the good and short counts). No row = the level's start. A row whose level
  isn't the plan's level is read as the new level's start (decision 4), so a level change
  needs no extra code path.
- **Applied when served, like strength targets:** the plan keeps the block's starting
  timing; the step replaces work and rest seconds when a pending workout is shown. Rounds
  and effort stay as built.
- **Which rows are intervals:** main-block rows of a HIIT workout and finisher rows, not
  swapped out. Warm-ups, cool-downs and steady cardio are never touched.
- **Level-up text stays honest (ADR 0022):** when moving up changes the user's interval
  timing, `what_changes` says so: "Intervals: 20 s on / 40 s off → 30 s on / 30 s off".
  No line when it doesn't change or the user has no intervals.

## Consequences
- Pure rules in `training/intervals.py`: the step scale and each level's start, top and
  floor (`RANGES`), `timing`, `start_timing`, `state_for` (level changes), `served_step`
  (comebacks), `verdict` (good / short / nothing), `after_workout` (runs of two) and
  `with_pair` (feedback pairs).
- New model `IntervalStep` (`models/progress.py`) and a migration adding `interval_steps`.
- `services/progress.after_finish` moves the step after a workout with intervals (not
  recovery, not comeback workouts) and returns it in the outcome; `services/plans`
  decides which rows are intervals (`is_interval`) and serves them with the user's timing
  (`interval_timing`); `plans.level_up_offer` adds the intervals line, and
  `level_up.WeekShape` knows whether a week has intervals.
- Checked before shipping: every interval row in 12,600 generated blocks (every goal,
  level, setup, 2–6 days, 10–90 minutes and no limit, limits, low intensity, blocks 1
  and 2) is a one-minute round at its level's start timing, so serving any step keeps the
  workout's length; no low-intensity block has intervals.
- API: `SessionResult.intervals` (`direction`: `up` / `down`, `work_seconds`,
  `rest_seconds`; null when nothing moved).
- Later: Tabata (20/10 × 8) as an experienced option; a "new personal best" moment in
  gamification (phase 4).

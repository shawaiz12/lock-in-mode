# 0022 – Moving up a level: "Ready for more?"

**Date:** 2026-11-23
**Status:** Accepted

## Context
The level from onboarding (ADR 0012: beginner, some experience, experienced) sets how much
work the plan gives: weekly hard sets per muscle (beginner 6–10, some experience 10–14,
experienced 12–18), exercises per session, and which routines are allowed (beginners get
full-body routines only). Progression (ADR 0019) raises the numbers *within* a level, but
nothing ever moves the level itself, so a beginner stays on beginner volume for good.

KB section 10: "Promote a beginner to some experience after 12 weeks with at least 2
sessions a week completed, or sooner if they pass all three: 15 push-ups, 25 bodyweight
squats, 45 s plank. Ask first ('ready for more?') instead of changing the plan silently."

## Decisions

### 1. Only beginners are offered a move up, for now (user's choice)
Beginner → some experience, the KB's rule. Nobody is offered "experienced": it means 2+
years of steady training, so no app user is near it yet, and progression keeps raising
the numbers within a level. Anyone can still change their level in the profile.
- ❌ "Both steps" was rejected: a second rule we'd have to invent, with no research behind
  it. ❌ "No offers" was rejected: most beginners would never notice they're ready.

### 2. The slow route: 12 good weeks, gaps pause the count (user's choice)
A **good week** is a 7-day stretch with at least 2 trained workouts (finished with at
least one ticked set: half a workout counts, ADR 0018). Weeks are counted in 7-day
stretches from the user's first trained workout, so time zones and weekdays don't matter.
12 good weeks **in total** earn the offer: a missed week or a holiday just doesn't add
one; it never wipes the count (brief principle 4). Comeback workouts (ADR 0021) count:
they're real training.
- ❌ "12 in a row" was rejected: one sick week would start again from zero. ❌ "24
  workouts in total" was rejected: at 6 a week that's 4 weeks, too soon for more volume.

### 3. The fast route: the three marks, from sets they log (user's choice)
All three, from **any set ever logged**, in any workout (the strength test included):
- **15+ reps** of a push-up, or of a harder move up the push-up ladder (close-grip,
  decline, archer);
- **25+ reps** of a bodyweight squat, or of a harder move up the squat ladder;
- **45 s+** of a plank, or of a harder timed move up the plank ladder.

"Harder" follows the library's `harder` links (ADR 0011), so the rule needs no list of
its own. Nothing extra to do. Gym users who never do these moves get there by the 12-week
route.
- ❌ "A short re-test workout" was rejected: an extra workout to schedule and explain.
  ❌ "No fast route" was rejected: fast learners would wait months for more volume.

### 4. Asked at "Block complete!"; yes builds the next block at the new level (user's choice)
When the block is complete and the user has earned it, `GET /plans/current` carries
`level_up`: the level offered, why (12 good weeks, or the three marks), and what changes
(see "What changes, honestly" below).
The block-complete screen asks "Ready for more?":
- **Yes** = `POST /plans {"level_up": true}`: the profile's level becomes some experience
  and the next block is built from it, in one transaction.
- **Not yet** = `POST /plans` as today: same level.

Nothing half-done is replaced, and the question lands on a moment that already feels like
a win (Retention knowledge, Source 2: block complete is the earned moment). Earned
mid-block = asked at the end of that block, at most 5 weeks later.
- ❌ "As soon as earned, change now" was rejected: it would throw away the rest of the
  block (a profile change replaces the plan, ADR 0017). ❌ "As soon as earned, change
  later" was rejected: the app would have to store and explain a "coming next block" level.

### 5. "Not yet" = asked again next block (user's choice)
Nothing is saved for a "not yet": the offer is worked out fresh at every block complete,
so it simply comes back about 5 weeks later, while they're still a beginner.
- ❌ "Never ask again" was rejected: "not yet" usually means "later". ❌ "In 3 blocks" was
  rejected: 15 weeks is a long wait after a busy month.

### 6. Low intensity users are offered it too, and keep every limit (user's choice)
Users who said "yes" on the safety screen (ADR 0012) can be offered the move up. Level only
changes **how much** work there is; `needs_low_intensity` keeps deciding **what kind**:
still no HIIT, no finishers, no cautioned exercises, gentler intervals. Their offer also
says `check_with_doctor: true`, so the app shows the safety screen's "check with a doctor
before pushing harder" line with it (brief principle 5).

The recommendation was "never offered" (their plan stays as it is until they redo the
safety screen). The user chose to offer it: 12 weeks of steady training is real evidence
of readiness for more sets, and the safety limits, which are what the "yes" is about,
don't change.
- ❌ "Offered like anyone" was rejected: it would drop the low intensity limits.

**Follow-up (user's choice): low intensity means 3 hard workouts a week at most, at any
level.** Building the plans showed the limits above didn't cover frequency: a
low-intensity user training 6 days would have gone from 3 hard workouts (plus easy
cardio and mobility) to 6 strength workouts, 42 → 78 sets a week. The beginner cap of 3
hard days (KB section 4) now also applies to anyone on low intensity, at any level, in
the muscle, strength and fat-loss routines (stamina and stay-active weeks already stay
at 3 or fewer once HIIT becomes steady cardio). Their reason line says "From your safety
check: 3 hard workouts a week at most". This also applies to users who picked "some
experience" or "experienced" in onboarding and said yes on the safety screen, from their
next block. Moving up still brings longer holds, harder moves as they're ready, and
splits within those 3 days.
- ❌ "Full routine, as chosen" was rejected: up to 6 hard days for someone with a heart
  condition or a pregnancy is more than the safety screen's "yes" allows for.
  ❌ "Don't offer it" was rejected: the cap makes the offer safe.

### 7. Not during a comeback (user's choice)
While a comeback is due or easing workouts (ADR 0021), there's no offer: "ready for
more?" in someone's first week back after two months off is the wrong question. It comes
at the first block complete after the comeback is over.
- ❌ "Comeback weeks don't count" was rejected: slower for people who take breaks, and
  eased workouts are still training. ❌ "No special rule" was rejected (see above).

### 8. Rules around it
- **Worked out on read, nothing stored:** good weeks and marks come from set logs. No new
  table and no migration.
- `POST /plans {"level_up": true}` when no offer stands (not a beginner, not earned, in a
  comeback, or no block yet) → 409 `level_up_not_offered`: the app showed an offer that is
  no longer there (e.g. the profile changed on another phone). A block that isn't complete
  still answers 409 `plan_in_progress`, as before.
- **Progress carries over** (ADR 0019): targets, weights and rungs stay, so nobody starts
  over.
- **What changes, honestly.** The offer's `what_changes` lines are worked out by building
  the next block's first week both ways (current level and offered level, exactly as
  `POST /plans` would build it) and saying what differs: "Hard workouts a week: 3 → 5",
  "Sets a week: about 42 → 50". Building the plans showed the level doesn't always add
  sets: in 20–30 minute sessions time is the cap, and "some experience" does 3 sets of
  each exercise, so fewer different exercises fit (24 → 22 sets in some cases). Then the
  line says "Your sessions stay 20 minutes, so the work gets harder rather than longer"
  instead of promising more. Plus: harder moves as they're ready, the safety limits (low
  intensity), and "your progress stays".
- A user who lowers their level in the profile later is offered the move up again at the
  next block complete if they still qualify (the count is their whole history).

## Consequences
- Pure rules in `training/level_up.py` (good weeks from workout times, the three marks,
  `week_shape` and `what_changes`). `training/routine.py`: the 3-hard-days cap now also
  applies to low intensity (`_three_hard_days_max`).
- `services/level_up.py` reads set logs and the library's ladders (models only);
  `plans.level_up_offer` adds the timing rules (block complete, no comeback) and builds the
  "what changes" lines; `plans.start_plan` takes `level_up` and changes the profile's
  level before building the block.
- API: `PlanRead.level_up` (`to`, `reason`: `good_weeks` or `strength_marks`,
  `good_weeks`, `check_with_doctor`; null when there's no offer); `POST /plans` takes an
  optional body `{"level_up": bool}`; new error code `level_up_not_offered` in
  docs/errors.md.
- Later: some experience → experienced (needs its own rule and research); a level-up
  moment in gamification (phase 4: XP, a rank-up screen).

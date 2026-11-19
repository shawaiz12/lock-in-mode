# 0012 – Onboarding and profile v2

**Date:** 2026-11-19
**Status:** Accepted

## Context
Onboarding is the most important part of the app. Fitness apps keep about 1 in 4 users
past day one and very few past day 30. Their one clear win is the **first finished
workout**: users who finish one come back far more often. So onboarding has a single job:
**get a new user to finish workout 1 today.** Every question has to change the plan or
how we talk to the user. Anything else is cut. The screen-by-screen flow is in
[docs/onboarding.md](../onboarding.md).

The Training Knowledge Base (section 2) needs inputs the `profiles` table can't hold yet:
a fifth goal, longer sessions with no upper limit, the push pull legs shoulder question
and the bro split opt-in. The brief also says "start immediately without an account".

## Decisions

### 1. Five goals
`Goal` gains `build_muscle`: build muscle, build strength, lose fat / get fit, improve
stamina, stay active. For beginners, build muscle and build strength give the same plan
(KB section 2). The plan generator decides this, not the profile.

Goals are stored as text (`native_enum=False`, see `enum_column`), so adding a value needs
**no database change**.

### 2. Session length: 10–90 minutes, or no limit
`minutes_per_session` becomes **nullable**. Allowed: 10, 20, 30, 45, 60, 75, 90, and
**NULL = no limit**.
- ✅ NULL is how SQL says "no value". The plan generator reads `None` and fills the
  template without trimming.
- ❌ `0` was rejected because it reads as "zero minutes". ❌ A big number like `999` was
  rejected because it leaks into time maths ("this workout takes 999 min").
- The CHECK constraint becomes `minutes_per_session IS NULL OR minutes_per_session IN (…)`.
  Autogenerate can't see CHECK changes, so the migration replaces it by hand.

### 3. Level comes from training history
The app never asks "how fit are you?" because people rate themselves badly. It asks how
long they've trained and stores the matching level:

| The user taps | Stored level |
|---|---|
| Never, on and off, or under 6 months of steady training | `beginner` |
| 6 months to 2 years, knows the basic exercises | `some_experience` |
| 2+ years, still making progress | `experienced` |

**No "coming back after 6+ months off?" question.** It's one tap fewer. The first-workout
test (decision 4) and the "too hard" feedback catch a rusty returner within a session or
two. This replaces the onboarding part of KB section 2's line "anyone returning after
more than 6 months off starts one level lower". The comeback rules for users who stop
*using the app* (KB section 10) still apply.

### 4. The first workout is the strength test
There is no test inside onboarding. Workout 1 has open targets ("as many as you can with
good form, stop with 2 left") and the engine places the user on each exercise ladder
from KB section 2's ability table. Gym users pick starting weights the same way.
- ✅ Onboarding stays short, and the test *is* the activation moment.
- ❌ A test inside onboarding was rejected: more screens before any value, and people guess
  or quit.
- No profile fields are needed. Where the results are stored is decided with the plan
  generator.

### 5. Bro split: an opt-in when the user qualifies
New column `prefers_bro_split` (bool, default false). The plan generator uses it **only**
when the user qualifies (KB section 4): gym, or home with dumbbells; 5 days; some
experience or more; goal build muscle; 45+ minutes or no limit.
- The API returns a computed `bro_split_available` with the profile, so the app shows the
  "Push pull legs (recommended) or bro split?" switch only when it applies. **The rule
  lives in one place (the backend).** The app never copies it.
- The preference is kept when the user stops qualifying (e.g. drops to 4 days). It simply
  isn't used, and it comes back if they return to 5 days.
- It's asked on the plan reveal screen, not as an onboarding question, so it costs no
  extra tap for most users.

### 6. Push pull legs: where shoulders go
New column `shoulder_day`: `push` (default) or `legs`. Not nullable, because there is
always an answer even if the user is never asked. The app asks only when the plan is push
pull legs, on the plan reveal screen. Other routines ignore it.

### 7. "What's made it hard before?"
New column `obstacles`, an optional multi-select list: `no_time`,
`dont_know_what_to_do`, `lose_motivation`, `get_bored`. It changes **tips, reminder
wording and quests, never the plan.** For example, `no_time` makes the app suggest
shorter sessions on busy days, and `get_bored` puts exercise swaps up front. Skippable, so
it's empty by default.

### 8. Safety screen: store the result, not the answers
`POST /me/safety-screen` takes four yes/no answers (heart condition, chest pain when
active, pregnancy, recent surgery or injury). It stores only `needs_low_intensity`
(any yes) and `safety_screened_at`.
- ✅ The raw answers are health data. Not storing them is data minimisation: there's
  nothing to leak, and nothing to protect under privacy law.
- The screen can be retaken. All "no" sets `needs_low_intensity` back to false (e.g.
  recovered from surgery).
- The plan generator will refuse to build a plan until `safety_screened_at` is set.

### 9. Profile endpoints
- `GET /me/profile` returns 404 `profile_not_found` when the user hasn't onboarded. The app
  uses that to decide between onboarding and the home screen.
- `PUT /me/profile` replaces the whole profile. It returns **201** the first time
  (created) and **200** after (updated). It never touches the safety fields.
- Validation errors are 422 `validation_failed`: a gym user can't list home equipment
  (gym means everything except bands, ADR 0010), the women-at-home track is home-only,
  and `gym` isn't a home equipment choice. Duplicate list items are removed, not
  rejected, so a small app bug can't block onboarding.
- **Guests can use all of these.** No sign-in is needed to onboard or train.

### 10. Sign-in: earn it first
This is a product rule. The backend already supports it (guest tokens, ADR 0005; linking
keeps progress, ADR 0006).
- The app creates a guest silently on first launch. Onboarding never shows a sign-in
  screen.
- The first "Save your progress" prompt comes **after workout 1 is finished**, when there
  is something to lose (XP, a level). After that it comes at milestones (first level-up,
  3-day streak). At most once a week, and "Not now" is the same size as the sign-in
  buttons.
- Honest wording: "Your progress is saved on this phone only. Sign in so it's safe if you
  change or reset your phone."
- Squads are the one feature that needs an account, because friends need a stable
  identity to find you.

### 11. No made-up numbers
Onboarding screens never show invented stats like "80% of users…". We have no users yet,
and trust is the product. They show promises the app keeps ("Missed a day? Your plan
moves forward. Nothing piles up.") and the KB's honest notes (fat loss mostly comes from
eating less than you burn). Real numbers can come once real data exists.

## Consequences
- Migration: add `prefers_bro_split`, `shoulder_day`, `obstacles`; make
  `minutes_per_session` nullable; replace its CHECK by hand. Downgrade maps no-limit and
  60+ minutes to 45, and `build_muscle` to `strength`, so it can't fail on new data.
- New error code `profile_not_found` in docs/errors.md.
- Follow-ups:
  - `PATCH /me` for the optional name on the welcome screen.
  - `DELETE /me` before the App Store: Apple requires in-app account deletion for any
    app that lets people create an account (guideline 5.1.1(v)).
  - Funnel events (which onboarding screen people quit on), so the flow can be tested
    and improved.
  - The women-at-home track keeps its name for now. If the app shows it to everyone as
    "quiet, small-space workouts", rename it in its own ADR.

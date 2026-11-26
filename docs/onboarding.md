# Onboarding playbook

The decisions behind this are in [ADR 0012](decisions/0012-onboarding-and-profile-v2.md);
[ADR 0036](decisions/0036-ui-redesign.md) cut the first run from 12 screens to 8 and added
the Lock In pact.
This page is the flow the mobile app builds: every screen, why it's there, and what it
sends to the API.

## The one job
**Get a new user to finish workout 1 today.** That's our activation moment. A user who
finishes one workout on day one is far more likely to come back. Every screen below either
moves them toward it or gets cut.

Rules for every screen:
- **One question per screen, one tap to answer.** Big buttons, no typing (except the
  optional name).
- **Every question changes the plan or how we talk to the user.** If it doesn't, it
  goes.
- **Say why.** Every question has one line saying why it's asked, and a progress bar shows
  how far along they are ("4 / 8").
- **Echo the answer back.** The goal's echo ("Build muscle: every part of each muscle gets
  trained…") shows at the top of the next question: proof we listened, no extra tap.
- **No sign-in, no paywall, no permission pop-ups before the workout.**
- **No invented numbers.** Show promises the app keeps, not fake user stats.
- **Lock In language.** The main button says "Lock In", not "Next".
- Target: 8 screens, about 9 taps, under a minute.

## The flow

| # | Screen | Asks / shows | Stored as | Why it's here |
|---|---|---|---|---|
| 0 | (silent) | App calls `POST /auth/guest` on first launch | guest user | They can start straight away. No account wall |
| 1 / 8 | Goal | "Let's build your plan." Build muscle · Build strength · Lose fat / get fit · Improve stamina · Stay active, each with a short line | `goal` | The "why" they downloaded the app. It shapes everything |
| 2 / 8 | Training history | The goal's echo on top (lose fat adds the honest note: "Fat loss comes mostly from eating less than you burn. Training shapes what you keep."). Never / on and off / under 6 months · 6 months–2 years · 2+ years | `level` | Self-rating is unreliable. History isn't |
| 3 / 8 | Where | Gym (moves on) · Home (then, on the same screen: Dumbbells · Bands · Pull-up bar, any mix or none, and "Quiet, small-space workouts", with a Lock In button) | `location`, `equipment`, `women_home_track` | Decides which exercises exist for them. No equipment is a full plan, not a lesser one |
| 4 / 8 | Days | 2 3 4 5 6, each with a line ("Most people start here"), never a promised split | `days_per_week` | Picks the routine (with goal and level) |
| 5 / 8 | Time | 10 · 20 · 30 · 45 · 60 · 75 · 90 · No limit | `minutes_per_session` (null = no limit) | Short sessions are a full plan too: "10 minutes counts." |
| 6 / 8 | Sore spots | Knees · Back · Shoulders (then Lock In) · None (moves on) | `limits` | Safety. We train around a sore area, we don't treat it |
| — | Save | `PUT /me/profile` | | One call with every answer (`obstacles` empty: not asked since ADR 0036) |
| 7 / 8 | Quick safety check | One list: a doctor said I have a heart condition · chest pain when active · pregnant · surgery or injury recently. "None of these" sends four noes in one tap; ticking any shows "Please check with a doctor first. We'll keep things gentle." | `POST /me/safety-screen` → `needs_low_intensity` only | Required before workout 1 |
| 8 / 8 | Lock In pact | "I train N days a week. Any week with 2 workouts counts. If I miss a week, I come back." + goal, where, minutes. Sign with a finger → LOCKED IN stamp, confetti, one buzz | `POST /me/pact` → `pact_signed_at` (the drawing is never sent) | A promise in their own hand, small enough to keep, with the comeback built in. Only before the first plan (`pact_due`) |
| — | Building your plan | 2–3 s. Shows the **real** reasons, one by one: "3 days → full body", "Knees → no jumping", "No equipment → push-up ladder" | `POST /plans` → `reasons` | People trust work they can see. Ours is real, so show it |
| — | Home | The HUD, the world card, this week, new bests, the muscle map, then the plan. Push pull legs → "Shoulders with push day or leg day?" If `bro_split_available` → "Push pull legs (recommended) or bro split?" | `shoulder_day`, `prefers_bro_split` (`PUT /me/profile` rebuilds the untouched plan, still block 1) | Choices asked here only matter to some users, so they cost everyone else nothing |
| — | Start | Big: **"Lock In: workout 1"** with "Full body A · about 45 min" under it. The reminder is offered on workout 1's finish screen (ADR 0034) | | One big button, always in reach of a thumb |

### Workout 1 is the test
Targets are open: "As many as you can with good form. Stop when you have 2 left." The
engine places them on each exercise ladder from the result (KB section 2). Before the first
set: "Stop if you feel sharp pain, dizziness or chest pain."

### After workout 1
1. **Celebrate:** XP, stat bars filling, "Level 2". This is the reward for locking in.
2. **Feedback:** too easy / just right / too hard (one tap).
3. **Save your progress?** Google · Apple · Not now (same size). Copy: "Your progress is
   saved on this phone only. Sign in so it's safe if you change or reset your phone."
4. **Next workout:** "Next: Thursday. Want a reminder?" A second workout is the next
   milestone, so point at it straight away.

## Sign-in prompts after that
- At milestones only: first level-up, 3-day streak, trying to join a squad (squads need an
  account).
- At most once a week. Never in the middle of a workout. Never blocks anything except
  squads.

## What `obstacles` would change (not asked since ADR 0036)

The question was cut because nothing used it yet. If one of these gets built, the
question can come back (as a skippable step after workout 1, not in the first run).

| Obstacle | What the app does differently |
|---|---|
| `no_time` | Offers a 10-minute version on busy days. Reminder: "10 minutes still counts." |
| `dont_know_what_to_do` | Shows the steps and form cues open by default. Tips before each new exercise |
| `lose_motivation` | Puts streaks and quests up front. Gentle comeback quests after a missed day |
| `get_bored` | Shows "swap this exercise" up front. Rotates exercises more often |

## What to measure (when funnel events exist)
- **Onboarding completion:** % of installs that reach screen 14.
- **Drop-off by screen:** where people quit. Fix the worst screen first.
- **Activation:** % who finish workout 1 on day one.
- **Second workout within 7 days:** the habit signal.
- Change one thing at a time and compare. Top subscription apps test their first-run
  screens all the time, and most apps never do.

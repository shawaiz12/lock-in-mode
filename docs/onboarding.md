# Onboarding playbook

The decisions behind this are in [ADR 0012](decisions/0012-onboarding-and-profile-v2.md).
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
- **Echo the answer back.** After a big answer, a short screen shows we listened ("Build
  muscle: we'll train every part of each muscle, 3–5 days a week"). This is what makes
  long quiz flows feel personal instead of tiring.
- **No sign-in, no paywall, no permission pop-ups before the workout.**
- **No invented numbers.** Show promises the app keeps, not fake user stats.
- **Lock In language.** The main button says "Lock In", not "Next".
- Target: about 10 taps, 60–90 seconds.

## The flow

| # | Screen | Asks / shows | Stored as | Why it's here |
|---|---|---|---|---|
| 0 | (silent) | App calls `POST /auth/guest` on first launch | guest user | They can start straight away. No account wall |
| 1 | Welcome | "You're the main character. Let's build your plan." Optional name | `PATCH /me` display_name (follow-up) | Sets the tone. A plan with their name on it feels like theirs |
| 2 | Goal | Build muscle · Build strength · Lose fat / get fit · Improve stamina · Stay active | `goal` | The "why" they downloaded the app. It shapes everything |
| 3 | Echo | One line on what their plan will do for that goal. Lose fat adds the honest note: "Fat loss comes mostly from eating less than you burn. Training shapes what you keep." | none | Shows we listened. Honest from screen one |
| 4 | Training history | Never / on and off / under 6 months · 6 months–2 years · 2+ years | `level` | Self-rating is unreliable. History isn't |
| 5 | Where | Home · Gym | `location` | Decides which exercises exist for them |
| 6 | Equipment (home only) | Dumbbells · Bands · Pull-up bar (any mix, or none). Toggle: quiet, small-space workouts | `equipment`, `women_home_track` | No equipment is a full plan, not a lesser one. Say so on the screen |
| 7 | Days | 2 3 4 5 6 | `days_per_week` | Picks the routine |
| 8 | Time | 10 · 20 · 30 · 45 · 60 · 75 · 90 · No limit | `minutes_per_session` (null = no limit) | Short sessions are a full plan too: "10 minutes counts." |
| 9 | Body limits | Knees · Back · Shoulders · None | `limits` | Safety. We train around a sore area, we don't treat it |
| 10 | What's made it hard before? (skippable) | No time · Don't know what to do · Lose motivation · Get bored | `obstacles` | Changes tips, reminders and quests (below) |
| — | Save | `PUT /me/profile` | | One call with every answer |
| 11 | Quick safety check | 4 yes/no: heart condition, chest pain when active, pregnant, recent surgery or injury | `POST /me/safety-screen` → `needs_low_intensity` only | Required before workout 1. Any yes: "Please check with a doctor first. We'll keep things gentle." |
| 12 | Building your plan | 2–3 s. Shows the **real** reasons, one by one: "3 days → full body", "Knees → no jumping", "No equipment → push-up ladder" | none | People trust work they can see. Ours is real, so show it |
| 13 | Your week | The plan. Push pull legs → "Shoulders with push day or leg day?" If `bro_split_available` → "Push pull legs (recommended) or bro split?" | `shoulder_day`, `prefers_bro_split` | Choices asked here only matter to some users, so they cost everyone else nothing |
| 14 | Start | Big: **"Lock In: start workout 1"**. Small: "Remind me later" (time picker, then the notification permission prompt) | reminder time | Asking for notifications only when they pick a time gets more "yes" than a cold pop-up |

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

## What `obstacles` changes

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

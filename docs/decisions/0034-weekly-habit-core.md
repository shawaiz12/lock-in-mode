# 0034 – The weekly habit core: ring, streak, new bests, reminder, retention report

**Date:** 2026-11-26
**Status:** Accepted

## Context
The brief's gamification plan (3.5) stacks XP, levels, 4 stats, daily quests, a weekly
"boss", streaks, ranks and squads. Checked against the retention notes
(`lock-in-mode/retention-knowledge.md`, Flags 1–4), four parts work against keeping people:
- a **daily** streak in a plan of 2–6 workouts a week pushes people to open the app, or
  train, on rest days, and turns "I want to" into "I can't miss today";
- **too many game layers at once** (Habitica: people managed the game instead of training);
- **friends-only** competition (Duolingo's didn't work; leagues of similar people did);
- **XP as the headline**: it rewards turning up, while feeling more capable is what keeps
  people training for years.

Two cheap wins came with it: offer a **reminder** on workout 1's finish screen (people who
set one stay longest), and **measure retention weekly, by finished workouts** (the action
that delivers the value, at the app's natural rhythm).

Separately: the rest beep was silent on his phones, online and offline, ringer on or off,
while the vibration worked.

## Decisions

### 1. A small weekly core first (his choice)
This stage: Home's weekly ring, a weekly streak with freezes, "New best" on the finish
screen, the reminder, and the retention report. XP and levels come next stage, in the
background. Squads (comparing effort, done vs planned, never strength) come after sign-in,
since they need accounts. Stats, daily quests and ranks are added one at a time later,
each kept only if weekly retention says it helps.

### 2. The ring: this week, done vs planned
"This week ●●○ 2 of 3 workouts" on Home (dots, no extra package). Planned = the profile's
days a week. A workout finished offline and not sent yet already counts on the ring.

### 3. The weekly streak (his choices: a minimum week of 2; earned freezes)
- Weeks run Monday to Sunday **on the phone's calendar** (its time zone is sent to the
  account, `PATCH /me` `time_zone`; UTC until then).
- A week is **kept with at least 2 trained workouts**, whatever the plan. Closing the full
  ring is the bigger win; the streak only asks for the minimum, so a hard week still counts.
- The streak = kept weeks in a row. This week joins once kept; until then it can't break
  anything.
- **Freezes:** one earned every 4 kept weeks, at most 2 held, used by themselves when a
  week is missed. A frozen week keeps the streak but doesn't add to it.
- Trained = finished with a ticked set (the same rule as the level-up's good weeks). Its
  time is the phone's finish time for offline workouts (ADR 0033), so a late sync lands in
  the right week.
- Worked out on read (`GET /me/week`, `training/week.py`), nothing stored: no migration
  for it, and a time-zone change re-buckets everything consistently.
- ❌ All planned workouts: more pressure, more breaks. ❌ Any 1 workout: says little.
- ❌ A free freeze each month: feels unearned. ❌ No freezes: harsh after illness or travel.

### 4. New bests: real progress as the headline
On finishing, each exercise's best in this workout is compared with every earlier one:
heaviest weight (weighted), most reps (sets without weight), longest hold. Main part and
finishers only; the first time a move is done is never a "best"; one per exercise, weight
first. Shown at the top of the finish screen ("New best: 14 reps of Push-up"), up to 3.
The finish screen also says when this workout kept the week ("This week counts: 3-week
streak").

### 5. The reminder
- **Offered on the first trained workout's finish screen** (`offer_reminder`), never
  before workout 1. Pre-filled: the plan's training days at the time they just finished
  (to the half hour). One tap "Remind me"; "Change" opens a sheet (time in half-hour steps,
  days); "Not now" closes it.
- Permission is asked only on that tap, right after a win. After a hard "don't ask again"
  the app doesn't ask: it says where to turn notifications on.
- **Local notifications** (expo-notifications, works in Expo Go): one per chosen day, once a
  week, at that time. No push server, no cost, no push entitlement (`enableRemoteNotifications:
  false`). Copy speaks to the feeling, never guilt: "Lock In Mode: on. Your next workout is
  ready. One tap and you're in."
- Saved on the account (`PATCH /me` `reminder`: `{at, days}`, null turns it off), so a new
  phone sets it up again by itself, without asking for permission. Changed or turned off
  on Home ("Reminder" card).
- Events `reminder_set` (days, hour) and `reminder_off`, for the report.

### 6. The retention report, weekly
The terminal report (ADR 0025) gains: a **weekly lifecycle** for the last 8 weeks (who
finished a workout: new, current, back after 1–3 weeks, back after 4+ weeks, went quiet,
kept the week); week 8 in the sign-up retention table; "Workout 2 finished" in the funnel;
reminder counts. Still from events, so "Share usage data" off keeps people out of it.

### 7. The silent beep
- The sounds are now **saved on the phone first** (`downloadFirst`): in Expo Go they streamed
  from the computer, so a workout opened offline had no sound.
- **No rewind before the first play**: the code rewound every sound before playing it, even
  one that had never played (and may not have finished loading).
- **Errors are no longer silent while developing**: they show in the Metro terminal as
  `[alerts] …`.
- A **Sound check** on Home plays the beep and says whether it loaded, and explains that the
  beep follows the media volume, not the ringer (a common reason for "only vibration").
- Not proven yet on his phones: this is the fix for every cause found in the code. If it
  stays silent, the Metro terminal line and the sound check say why.

## Found while building
- Expo's notification weekdays are 1–7 with **1 = Sunday**; ours are 0–6 with 0 = Monday.
  Converted in one tested function (`toPhoneWeekday`).
- "Freeze only when a streak runs" can't change anything under these rules (a streak only
  ends once freezes are gone), so that check was removed rather than kept untested.
- The plan's suggested `weekdays` already use 0 = Monday: the reminder's default days.
- `eslint-plugin-import` can't see `AndroidImportance` through `import * as`; named imports.
- Home now loads expo-audio (the sound check): Jest gets a small expo-audio fake too.

## Consequences
- DB: `users.time_zone`, `users.reminder_at`, `users.reminder_days` (nullable; old code keeps
  working while it migrates). Autogenerated by him after extracting the zip.
- API: `GET /me/week`; `PATCH /me` `time_zone` and `reminder`; `GET /me` shows both;
  `SessionResult` gains `new_bests`, `week`, `offer_reminder`. New events `reminder_set`,
  `reminder_off`.
- App: `ui/week.tsx` (WeekCard, ReminderOffer, SettingsCard, ReminderSheet, SoundCheck),
  `state/reminders.ts`, `features/week/words.ts`; finish screen and Home updated;
  `expo-notifications` added; `me` kept on the phone for offline.
- Next stage: XP and levels in the background. Then sign-in, then squads.

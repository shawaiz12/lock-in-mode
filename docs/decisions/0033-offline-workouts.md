# 0033 – Offline workouts: train with no signal, sync later

**Date:** 2026-11-25
**Status:** Accepted

## Context
The workout player (ADR 0032) needed a connection the whole time: every tick was a PUT,
and a failed one showed "not saved · Retry" and blocked finishing. Gyms are often in
basements, and the brief (3.4) says the player "works offline once a workout is
downloaded". The app also couldn't even open without a connection: the profile and the
plan were fetched at every launch.

One thing in the API made this more than an app change: the server stamped every set
with **its own time when the request arrived** (`logged_at = now()`). A workout done
offline and synced three days later would look three days late. That time drives breaks
and comebacks (ADR 0021: "last trained") and the 12 good weeks of the level-up (ADR 0022).

## Decisions

### 1. Start and finish offline, not just survive a dropped signal (user's choice)
Once the next workout is on the phone, it can be started, trained and finished with no
signal at all; everything syncs when the phone is back online.
- ❌ "Start online only, then keep sets through signal drops": simpler, but a gym with no
  signal at the door could never start.

### 2. The phone's time counts, checked by the server (user's choice)
The app sends when each thing happened on the phone: `started_at` on POST /sessions,
`logged_at` on each set's PUT, `finished_at` on the finish. All three are optional (an
older app sends none and gets the server's time, as before) and must carry a time zone
(a time without one is refused: 422).

The server never stores a phone time as-is. It moves it into order, in SQL, against the
database's own clock (`_kept_between`, `services/sessions.py`):
- **nothing after now:** a phone clock that's ahead becomes the database's now;
- **a start never before the plan existed or the last finished workout;**
- **a set never before its workout started;**
- **a finish never before its last set.**

So a wrong phone clock can't put a workout in the future or before an earlier one, and
the workouts stay in the order they were done. Continuing a workout keeps its first start.
- ❌ "The time it reaches the server": no API change, but a late sync would count late,
  could start a comeback that never happened, and could break a "good week".
- I first described this as "refuses times in the future"; built, refusing would throw a
  real set away for a clock two minutes fast. Moving the time into order keeps the set and
  gives the same protection.

### 3. A break is judged by when they trained
Starting with `started_at` works out the queue **as of that moment** (`queue_of(...,
now=)` → `comeback.find(now=)`). Trained 20 days ago, offline 18 days ago, synced today:
2 days away, no comeback. Without this the sync itself would have created a comeback.

### 4. One workout ahead (user's choice)
The phone keeps the next workout ready, not two. After an offline workout, the next one
needs one connection: its numbers depend on how this one went (progression, ADR 0019,
runs when the finish reaches the server).
- ❌ "Next two": the second would be a step behind on weights and reps.

### 5. The journal: everything goes on the phone first
The player no longer sends anything itself. Every tick, change, untick and the finish is
written to a small journal on the phone **at once** (a synchronous write, before the screen
redraws), then sent from there in order: the start, each set change, the finish. Online
that's a moment later; offline it's when the phone is back. So the player works the same
with or without a connection, and closing the app mid-set loses nothing.
- Each set counts its changes (`version`) and the changes the server has (`sent`). A
  change made while an older one is on its way just stays different and goes next.
- Every request is safe to repeat (continue, PUT, "already finished"), so a request whose
  answer was lost is simply sent again.
- Failures: no connection, 429 or 5xx → try again (after 5 s, 15 s, 30 s, then every
  minute; at once when the phone comes online or the app comes to the front). A set the
  server refuses (finished elsewhere, exercise gone) is dropped and the rest carries on.
  The plan moved on (409 `not_next_workout` at the start) or the sign-in ended → the
  journal can't be saved, and the plan screen says so once. "Already finished" on the
  finish → it got there before; only its answer was lost.
- Finishing is never refused any more ("some sets aren't saved" is gone): the finish waits
  in the journal behind the sets.
- One journal at a time (decision 4). Pure rules in `features/offline/journal.ts` and
  `sync.ts`; the running store (saving, retries, triggers) in `state/journal.tsx`.

### 6. What's kept on the phone, and for how long
TanStack Query's cache is saved on the phone (persist-client, a second after a change)
and read back at launch: the profile, the plan, workouts, exercise pages, the open
session. The plan screen downloads the next workout and its exercise pages whenever it's
online. Kept **14 days**: a copy downloaded longer ago than that can't start offline
("connect once"), because after two weeks away the plan eases you back in (ADR 0021) and
an old copy wouldn't know.

The app now opens offline from what's saved. Only a first launch with nothing saved asks to
connect once.

### 7. What needs a connection
Swaps and "show another" (the server picks the replacement and needs every set first), "where
does it hurt", changing answers, skipping a workout, starting the next block, a workout
that isn't on the phone. Offline, each says so instead of waiting forever. If an exercise
hurts offline: stop and skip it.

### 8. What the person sees
- Plan, offline: "Workout N is on this phone, ready to go."
- Player: a calm note "2 sets are saved on this phone. They sync when you're online."
  (not a warning: nothing is wrong).
- Finished offline: "Locked in. Saved on this phone. It syncs when you're online…"; the
  plan shows "Workout N · saved on this phone" and "Connect to get your next workout".
- Once it syncs: the finish screen's "what changed" shows on the plan ("Done offline,
  synced just now"), then the next workout is ready.

## Found while building
- **The server used two clocks**: a new set got the database's `now()`, a re-ticked set
  and every finish got the app server's clock. Phone times are now kept against the
  database's clock only; the no-time path stays as it was (backwards compatible).
- **A "last set" floor for a start was redundant**: a finish is never before its own sets,
  so "after the last finish" already covers it. Removed rather than kept untested.
- **TanStack Query on a phone never knows it's offline** unless something tells it:
  `expo-network` now feeds its `onlineManager`. Only a network the phone *knows* has no
  internet counts as offline; unsure counts as online, and a failed request is retried.
- **Offline, queries and mutations wait instead of failing**: a screen with nothing saved
  showed a spinner forever, and a swap would have waited silently. Each screen now says
  what needs a connection; swaps run with `networkMode: 'always'` and fail with a clear
  line.
- **The cache dropped anything unused for 5 minutes** (TanStack's default), and the saved
  copy with it: the downloaded workout would vanish. Kept 14 days now.
- **A saved "plan just created" replayed "Building your plan" on every offline launch**:
  it's marked seen once shown.
- **The repo's AGENTS.md prefers Expo modules**: `expo-sqlite/kv-store` (AsyncStorage-
  shaped, plus synchronous writes) instead of the community AsyncStorage. The synchronous
  write is what makes "every tick on the phone before the screen redraws" possible.
- **Expo Router's test renderer can't render the app twice in one test**: "app closed and
  reopened" tests write the saved cache and journal straight into the fake storage, in
  the app's own format; another test checks the app really writes that cache.
- **Funnel events (ADR 0025) still carry the time the server received them**, so an
  offline workout's `workout_started`/`workout_finished` events arrive late. Fine for
  funnel counts; worth knowing before reading them by day.
- Known edge: if a break starts AFTER the workout was downloaded (under 14 days), the
  offline workout shows the normal numbers. The server still judges the break by the start
  time, links the workout to the comeback, and comeback workouts change no progress, so
  nothing is pushed from it.

## Consequences
- API: optional `started_at`, `logged_at`, `finished_at` (aware datetimes) on POST
  /sessions, PUT a set, POST finish. No new endpoint, no new error code, **no migration**.
- App: `features/offline/` (journal, sync: pure, tested), `state/journal.tsx`,
  `state/online.ts`, `state/persist.ts`, `state/ready.ts`; the player reads and writes the
  journal; plan, preview, play and start screens know offline. `jest.setup.js` fakes
  expo-sqlite's store and expo-network (`src/test/`).
- New packages (SDK 58, all in Expo Go): `expo-sqlite`, `expo-network`,
  `@tanstack/react-query-persist-client`, `@tanstack/query-async-storage-persister`.
- Not covered yet: Google/Apple sign-in (development build), "Exercises you swapped out",
  home screen, app-side events, offline for anything but the next workout.

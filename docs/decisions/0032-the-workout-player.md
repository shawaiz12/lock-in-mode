# 0032 – The workout player: doing a workout on the phone

**Date:** 2026-11-25
**Status:** Accepted

## Context
The app could show a plan and a read-only workout (ADR 0029), but not train with it. The
API for training has existed since ADR 0018–0023: start or continue a session, PUT one set
at a time, swap, skip, finish with optional feedback, and a finish response that says what
moved. The brief (3.4) asks for a guided, step-by-step player with timers for timed sets,
rest and HIIT, one-tap logging pre-filled from the plan, and offline workouts. The plan
screen promised "the next block comes with the workout player".

## Decisions

### 1. Scope: the player and the finish screen, online (user's choice)
Start → warm-up → every set → cool-down → "How did that feel?" → what changed → back to
the plan, plus "continue" for an open workout, skip, swaps, and the next block. Needs a
connection during the workout; offline is the next stage.
- ❌ "Player + finish + offline" in one go: about twice the code and much harder to test.
- ❌ "Player only": the finish screen is where progression becomes visible.

### 2. One station per screen (user's choice)
A *station* is what's done together: the warm-up, one exercise (straight sets), a superset
pair, a whole circuit round, a HIIT block, a finisher, steady cardio, the cool-down. The
screen shows the current set big, the station's other sets below with ticks, and a
progress bar (sets done of all sets). The order and rests copy the server's own time model
(`training/sessions.py` `estimate_seconds`), so what the app does is what the plan's minutes
assumed:
- straight sets: rest after every set, including before the next exercise;
- superset: A, B, rest; a round's rest is the longest of the pair; when the pair has
  uneven sets (a 4-set row with a 2-set press in 30-minute sessions) the shorter one drops
  out of the later rounds;
- circuit: every move in turn with its rest, then at least 60 s between rounds;
- HIIT and finishers: work, rest, next move, round after round, all by themselves;
- no rest before the cool-down or at the very end.
- ❌ "One scrolling checklist": faster to scan, harder to follow mid-set.

### 3. Tap to tick, tap the numbers to change them (user's choice)
Every set shows what one tap will log ("✓ 8 reps · 40 kg"). Different numbers: tap them,
then − / + (or type). Weights step like a real gym, the same steps as progression (+2.5 kg
dumbbells, +5 kg machines and lower-body bars…). Strength-test sets ask "How many did you
do?" (reps) or run a stopwatch (holds). Practice sets ("light warm-up set") are ticked but
never sent. A ticked set can be changed or unticked from the list.
- **Pre-fill:** the suggested weight (progress, else last time's); reps = what they did
  last time *at that same weight*, kept inside today's range; a new weight or no history
  starts at the **bottom** of the range. Never the top by default: progression steps up
  when every set hits the top (ADR 0019), so the top has to be something they did, not
  something they tapped through.
- Weight is never required: some gym moves have no weight (ab wheel), and "no weight yet"
  is allowed.
- ❌ "Enter numbers every set": the brief's number one reason people quit.

### 4. Rest starts by itself, with a buzz and a beep (user's choice)
Ticking a set starts its rest (+15 s and Skip rest). The end of a rest or a timed move
beeps and buzzes; short beeps at 3, 2, 1 seconds. Timed moves start with one tap; in the
warm-up, cool-down, HIIT and finishers one tap runs the whole station (pause, skip a move,
stop early). The screen stays on while the player is open.
- The beep plays **even with the ringer on silent** (his call after trying it on the
  iPhone: at the gym the phone is usually on silent, and the beep is the point), mixes
  with the person's music without stopping it, and the volume buttons set how loud it
  is. A light haptic tap confirms each tick. (First version respected the silent switch:
  tried on the phone, the beep was missing exactly when it mattered.)
- Timers store when they end, not seconds left, so a late frame or a locked phone never
  makes them drift; they catch up the moment the app is back.
- ❌ "Manual rest": one more tap per set.

### 5. Sending sets: at once, in order, never lost silently
A tick shows done immediately and is sent in the background (PUT, safe to repeat). Sends
for the same set wait for each other (tick then untick can't arrive the other way round).
A failed send shows "1 set isn't saved yet · Retry", and **finishing waits for every send
and refuses while any failed**: sets are locked once a workout is finished.

### 6. Leaving and continuing
"‹ Leave" (or the phone's back button) keeps the workout open on the server. The plan
screen then says "Lock In: continue workout N", and the player picks up at the first set
not logged (worked out from the server's sets, never stored on the phone). Swiping back is
off in the player so a stray swipe mid-set doesn't leave.

### 7. Swaps, skipping, finishing early
"More" lists, per exercise on the screen: How to do it (steps, cues, common mistake, from
the library), "This hurts: swap it", "Show another (today only)"; then "Skip this
exercise" and "Finish workout now". After "This hurts" the app asks once, optionally, where
it hurt (ADR 0020 decision 3); a suggested limit is offered on the result screen, after the
workout, because saving the profile rebuilds the plan. Finishing early is never shamed:
"5 of 12 sets. Half a workout counts." The preview offers "Skip this workout" with one
confirmation, only before it's started.

### 8. The result screen and the next block
"Locked in." with the sets logged, the strength test's starting points, what steps up,
what eases off (said as calmly as going up), the HIIT timing, earned recovery, and "Block
complete". At the end of a block the plan screen shows "Ready for more?" with its own lines
when a level-up is offered (ADR 0022), else "Lock In: start block N+1".
- **Guests' "Protect your progress" (ADR 0026):** the card shows the real summary lines
  and says sign-in comes in the next app update. Google/Apple sign-in needs a development
  build (not Expo Go), so it's its own stage. The server records `sign_in_offered` either
  way; a milestone passed now isn't offered again (his earlier choice), which only affects
  test accounts so far.

## Found while building
- **expo-audio's config plugin asks for the microphone by default** (iOS microphone text,
  Android RECORD_AUDIO) and for background audio. `npx expo install expo-audio` adds the
  plugin with those defaults; an app asking for the microphone without using it gets
  questions in store review. `app.json` configures it off: `microphonePermission: false`,
  `recordAudioAndroid: false`, `enableBackgroundPlayback: false` (checked with
  `npx expo config`: no RECORD_AUDIO, no microphone text, no background mode).
- **Strength-test holds have no time target** (the plank test is `seconds: null`): only the
  library knows it's a hold (`is_timed`). The player loads each exercise's library page
  (also used for "How to do it" and to know weighted moves); if one fails to load, the
  player still works with what the workout says.
- **A one-tap pre-fill at the top of the range would make everyone "progress" every
  workout** (decision 3).
- **openapi-fetch gives no `data` on a 204** (untick): it needed its own unwrap.
- **Finishing with a failed send would lose that set for good**, because finished sets
  are locked (decision 5).
- **"Weighted" by kit includes gym moves with no weight** (ab wheel): weight stays optional.
- Checked against the real API: the app's exact call order (warm-up moves as seconds, no
  practice sets, circuit and HIIT rounds as set numbers, a swap mid-workout, finish with
  each feedback) for 4 kinds of user × 4 workouts: straight sets, 30-minute supersets,
  circuits, HIIT, steady cardio. Every call answered 200; progress, placements and HIIT
  timing came back as ADR 0018–0023 say.

## Consequences
- New: `src/app/workout/[id]/play.tsx` (the old preview moved to `workout/[id]/index.tsx`,
  same address), `src/state/player.ts`, `src/features/player/` (steps, entry, clock, words,
  result: pure, tested), `src/ui/player.tsx`, `src/ui/alerts.ts`, `assets/sounds/` (two
  short tones made for the app), kit `Sheet`, `Stepper`, `OutlineButton`, `ProgressBar`.
- New calls in `endpoints.ts`: exercise detail, open session, start, log/delete set,
  finish, skip, swap, where it hurts, next block.
- New packages (SDK 58 versions): `expo-audio`, `expo-haptics`, `expo-keep-awake`. All
  are in Expo Go.
- No API change, no migration.
- Not covered yet: offline workouts (next), Google/Apple sign-in (development build), an
  "Exercises you swapped out" screen with "bring it back", alerts while the app is in the
  background (needs notifications), demo GIFs, a home screen, app-side events.

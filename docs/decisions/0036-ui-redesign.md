# 0036 – The Lock In look: a shorter first run, the pact, the muscle map, Settings

**Date:** 2026-11-26
**Status:** Accepted

## Context
The app worked but looked like a black-and-white prototype with zero UX (his words). He
recorded the apps he likes (Brainrot, Cal AI), added Bread and Skillion as references,
picked the colours himself in a colour lab, and approved the mockups
(`lock-in-mode/ui-redesign.md`). The rules come from `lock-in-mode/ui-knowledge.md`
(contrast, Nielsen Norman's onboarding advice) and `lock-in-mode/retention-knowledge.md`
(no shame, real progress first). Sign-in is postponed (it needs a development build, and
the $99/year Apple membership on iPhone), so this stage is everything that works in Expo Go.

## Decisions

### 1. The look (his picks)
- **Light mode:** warm cream ground `#FFE9BD`, cards `#FFF6E3`. **Dark mode:** pure black
  `#000000`, cards `#141414`. **Light or dark follows the phone** (`userInterfaceStyle:
  automatic`, `useColorScheme`); there's no switch in the app.
- **Brand orange `#E14705`** for rings, icons and the muscle map. The big button is
  `#D44204` so its white text passes 4.5:1 (his `#E14705` gives 4.1:1).
- **Gold `#FFB800` means rewards only**: XP, the streak flame, new bests. He first picked
  red; changed after the flag that red is 1.08:1 against the orange and reads as "error".
  Gold on cream gets a dark outline (it's 1.4:1 alone); gold *text* in light mode is
  `#8A5A00`.
- **Chunky pieces:** cards with a 2 px edge and a 5 px bottom lip, a big button that
  presses down like a key, 14 px outlined bars. **Rubik** for all text (bold, slightly
  rounded; `@expo-google-fonts/rubik`, one font file per weight).
- Colours have roles, never names (`card`, `muted`, `brand`), in `src/ui/theme.ts`; every
  style is made per mode by `makeStyles` and reused.

### 2. A shorter first run: 12 screens → 8 (his ask)
He found onboarding too long. Each screen was checked against the playbook's own rule
("every question changes the plan, or it goes"):
- **Welcome + name: cut.** Neither changes the plan. The pact's signature is theirs; the
  name moved to Settings.
- **The goal's echo: moved** to the top of the next screen (same honest fat-loss note).
- **Home kit: on the "where" screen**, shown after tapping Home.
- **"What's made it hard before?": cut.** It was stored but nothing used it yet. Profiles
  are saved with no obstacles; it can come back where it changes something.
- **Safety: one list** with "None of these" (one tap for most people) instead of four
  yes/no pairs. The server still gets all four answers and keeps only the result.

Now: goal → experience → where (+ kit) → days → time → sore spots → safety → **pact**,
one progress bar ("4 / 8") across all eight, a back button, and one line on every
question saying **why** it's asked (Nielsen Norman: brief, explain why, show progress).
Single answers move on by themselves. Days get a number badge and a line each, never a
promised split (the routine depends on goal and level too).

### 3. The Lock In pact (his pick), the last step
A paper card with their own promise: "I train N days a week. Any week with 2 workouts
counts. If I miss a week, I come back." plus goal, where and minutes. They **sign with a
finger** (his choice over press-and-hold: effort makes a promise feel real); "I'm locked
in" stamps it LOCKED IN with confetti and one buzz, then the plan opens.
- **The drawing is never sent or stored.** `POST /me/pact` saves only the date
  (`profiles.pact_signed_at`), once; signing again keeps the first date. A `pact_signed`
  funnel event. Changing answers keeps it.
- **Only before the first plan.** The server says when it's due (`pact_due` on the
  profile: safety done, not signed, no plan ever). Someone who already trains, maybe
  offline mid-workout, is never sent to a screen that needs a connection. A profile saved
  by an older app has no `pact_due`: that's "no".
- Screen readers can't draw: the pad is also a button ("Sign here") that signs for them.

### 4. Home
- **HUD:** the level badge, "Lock In level 4 · 180 / 400 XP" with a gold bar, the streak
  chip, the Settings gear.
- **The world card:** where the character will live (a placeholder figure until the model
  sheet is approved). It says the next step ("1 more this week?", "This week counts!"),
  never a loss; the streak line runs along the bottom. It never decays.
- **Tiles:** this week's ring ("1 of 3 workouts") and **every new best so far**
  (`GET /me/bests`, counted exactly like the finish screens count them, so it only grows).
- **The muscle map** (his pick: front and back, tap for heads). See 5.
- Then the plan as before (block, choices, weeks, why), and the big button with a second
  line: "Lock In: workout 5 · Pull · about 45 min".

### 5. The muscle map: `GET /me/muscles`
Every muscle group and every head, always all of them, with the ticked sets this week and
whether the next workout trains it:
- A set counts once for each head its exercise targets (`Exercise.targets`) and once per
  group. Only main and finisher sets (not warm-ups); only workouts finished this week
  (Monday to Sunday on the phone's calendar, like `GET /me/week`).
- "Next up" = the targets of the next workout's exercises that aren't swapped out.
- The phone draws a front and a back body (back muscles are invisible from the front):
  orange = trained, dashed = next, plain = not yet. Tapping opens every head with its sets
  ("Rear delts · Not yet"): his rule is that every head of a trained muscle counts.
- A drawing of where the work went, not anatomy: no exercise isolates one head.

### 6. Settings (his pick)
Your name; the reminder and the sound check (moved from Home); **rest beep and vibration
switches** (this phone's own settings, kept with no connection; the set-tick tap and the
celebration buzz follow vibration); "Share usage data"; **Download my data** (the export
becomes one JSON file and the phone's share sheet opens: Files, Drive, email); **Delete
account** (asks first, offers the download, an optional reason, then a red "Delete for
good"; the phone then starts again as a brand-new guest with nothing of the old account
left). **Sign out comes with sign-in**: a guest who signed out could never get back in.

### 7. The workout player and the finish screen
The same steps, restyled: big numbers you can read mid-set, and "tap a number to change
it" boxes (kg, reps, seconds). The finish screen's cards: a gold-edged "Real progress"
card with a trophy, the kept week with a tick, "XP earned" counting up, the gold level
bar.

## API
- `GET /me/muscles` → `{week_start, groups: [{group, sets, next_up, heads: [{head, sets,
  next_up}]}], next_workout}`.
- `GET /me/bests` → `{total}`.
- `POST /me/pact` → the profile (404 `profile_not_found` before onboarding).
- The profile gains `pact_signed_at` and `pact_due`.

## Data
One migration (down_revision `2bfa835eddfd`): `profiles.pact_signed_at` (timestamptz,
nullable). Autogenerate sees it; no helper script. `pact_signed` is a new event name (text
column, no migration).

## Packages (Expo Go has all of them)
`@expo-google-fonts/rubik`, `expo-font`, `react-native-svg` (rings, body map, signature,
icons), `expo-system-ui` (the background behind screens in light/dark), `expo-file-system`
+ `expo-sharing` (Download my data).

## Consequences
- ✅ New people reach their plan in 8 screens and about 9 taps instead of 12 and 16, every
  answer the plan uses still asked.
- ✅ The look works in light and dark, follows the phone, and every text passes contrast.
- ✅ Two new Home reasons to come back that are real progress, not points: every best so
  far, and this week's muscles.
- ✅ People can take their data and leave without asking anyone (store requirement).
- ⚠️ The pact is only for new people: he sees it after "Delete account" (a fresh start).
- ⚠️ The obstacles question is gone; bring it back only with something that uses it.
- ⚠️ The world card's figure is a placeholder until the character model sheet.
- Later: "Change my answers" in Settings (the mockup has it), sign out with sign-in, an
  in-app light/dark override if people ask, the character in the world card.

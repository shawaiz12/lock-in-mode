# 0029 – Mobile app foundation: first launch to the plan

**Date:** 2026-11-24
**Status:** Accepted

## Context
Phase 3 starts the app the API was built for. The brief fixes the stack (React Native +
Expo + TypeScript, one codebase for Android and iOS, Expo push and EAS builds later) and the
repo layout (`mobile/` next to `backend/`). docs/onboarding.md already lists every first-run
screen and the call behind it. The user tests on **both** an Android phone and an iPhone with
Expo Go, from the office Linux PC. First React Native code for him: everything is explained
with .NET/Unity comparisons (mobile/README.md).

Checked on 2026-11-24: Expo SDK 58 is current (React Native 0.88, React 19.3, TypeScript 6);
Expo Go runs one SDK at a time and can be installed for a given SDK from expo.dev/go.

## Decisions

### 1. Scope of this stage: first launch → plan (user's choice)
Silent guest sign-in → onboarding (screens 1–10) → safety check (11) → "Building your plan"
with the real reasons (12) → the plan with its two small choices (13) → a read-only workout
preview. The workout player, finish screen and sign-in offers are the next stage.
- ❌ "The whole loop in one go": too much new code to spot-check at once.
- ❌ "Skeleton only": too slow.

### 2. Expo SDK 58, TypeScript strict, Expo Router
File-based screens in `src/app/` (like Razor Pages). Strict TypeScript plus
`noUncheckedIndexedAccess`. Dark, black-and-white UI from a tiny kit (`src/ui/kit.tsx`), the
logo's style; no UI library yet.
- **Found while building:** `npx expo install` couldn't reach Expo's version service from the
  build machine, so versions were taken from the official SDK 58 router template
  (`create-expo-app --template default@sdk-58`). Run `npx expo install --check` on a normal
  connection to confirm (mobile/README.md).

### 3. One stage drives navigation
`src/state/startup.ts` turns the sign-in and the profile into a stage: `loading`, `error`,
`onboarding` (404 `profile_not_found`), `safety` (`safety_screened_at` null) or `plan`. The
root layout opens only that stage's screens with `Stack.Protected`; when a save changes the
cached profile, the stage changes and Expo Router moves the person. No screen navigates by
hand after a save, and a deep link to `/plan` before onboarding lands on onboarding.
Guards are client-side only; the API still enforces everything (e.g. 409
`safety_screen_required`).

### 4. Server data through TanStack Query
Queries for session, profile, plan and workouts; mutations for saves, which write their result
straight into the cache. Retries: network errors and 5xx twice; never 4xx or a lost sign-in.

### 5. A typed client generated from the API's OpenAPI schema
`openapi-typescript` writes `src/api/schema.d.ts`; `openapi-fetch` uses it, so a wrong path or
field is a compile error. `npm run api:types` regenerates it from the running API. **CI checks
the committed types match the backend in the same commit** (the schema is exported from the
backend code, no server needed). Every call and its "what does this 404 mean" rule lives in
`src/api/endpoints.ts`.
- **Found while building:** `openapi-typescript` 7 declares TypeScript 5 as a peer, Expo 58
  ships TypeScript 6. An npm `overrides` entry lets it use ours; the generator was run and its
  output type-checks. Its default treats any field with a default as always present, which is
  wrong for request bodies (`PATCH /me` may leave `share_usage_data` out), so it runs with
  `defaultNonNullable: false`; fields the API always returns are `required` in the schema.

### 6. Sign-in: silent guest, tokens in the OS's secure storage, one refresh at a time
- First launch calls `POST /auth/guest` (playbook screen 0). The token pair is saved in
  `expo-secure-store` (Keychain / Keystore) as one JSON value, never in plain AsyncStorage.
- Every call goes through `authedFetch`: adds the bearer token, refreshes 30 s before expiry,
  and on a 401 refreshes once and resends the call (the body is copied first).
- Refresh tokens are single use with reuse detection (ADR 0005): two refreshes at once would
  look like theft and sign the person out. Only one refresh runs; other calls wait for it,
  and a call whose 401 arrives after someone else refreshed uses the new token.
- A refused refresh (401 `invalid_refresh_token`) forgets the sign-in and shows "Your sign-in
  has ended" with Try again, which starts a new guest. Offline or 5xx keeps the tokens.
- **No sign-out for guests:** signing a guest out makes them a lost guest, erased within an
  hour (ADR 0027).
- Platform difference (Expo docs): Android deletes secure storage on uninstall, so reinstalling
  starts a new guest; iOS usually keeps it. "Protect your progress" (ADR 0026) matters most on
  Android.

### 7. Onboarding as rules + one screen
`src/features/onboarding/flow.ts` holds the steps (equipment at home only), the options, the
"echo" lines and the mapping to `PUT /me/profile` (history → level, "No limit" → null, home-only
answers cleared for the gym, which the API would refuse). Single choices move on by themselves;
multi choices and info screens have "Lock In". One `PUT /me/profile` at the end, then
`PATCH /me` for the optional name. Echo lines promise only what the plan generator really does
(checked against `training/routine.py` and `sessions.py`).

### 8. Plan screen
First visit: `GET /plans/current` → 404 `plan_not_found` → `POST /plans` (a 409 from a parallel
build just re-reads), and the plan's own `reasons` appear one by one (700 ms each). Then block,
routine, weeks, a highlighted next workout and one big bottom button ("Lock In: workout N",
opening the preview for now). Push pull legs: "Shoulders with push day or leg day?"; when
`bro_split_available`: "Push pull legs (recommended) or bro split?". A change saves the full
profile and refetches the plan, which the server rebuilt (untouched, still block 1; verified
against the real API).

## Testing
- Unit tests for every rule (auth, endpoints, onboarding flow, safety answers, labels, stage).
- **The first-run journey through the real screens and navigator** (`expo-router/testing-library`)
  with the API faked: launch → onboarding → safety → reveal → plan → workout preview, plus
  "opens on the right screen", "can't deep-link past onboarding" and "error, then Try again".
- 20 deliberate breaks of the rules, each caught by a test.
- Once, by hand: the app's real API layer against the real local API (guest, profile, name,
  safety, plan build and read, preview, shoulder-day rebuild, token refresh): all worked.
- Metro bundles for Android and iOS.
- **Found while building:** the router test renderer switches Jest to fake timers, so TanStack
  Query's `setTimeout(0)` notifications are delivered at once in that test, time is moved in
  small steps, and taps are awaited (Testing Library 14 events are async). TypeScript 6 loads no
  `@types` automatically: `tsconfig` lists `jest`.

## Consequences
- CI gains a mobile job: type check, lint, tests, API types match.
- Expo Go only runs modules bundled into it: fine for now (secure-store is included). Google
  and Apple sign-in will need a development build (EAS), plus OAuth client ids and the bundle
  id / package name, which aren't set yet (`app.json`).
- The template's icons are placeholders until the logo is exported.
- Later: workout player with timers, finish screen (feedback, progress, intervals,
  `sign_in_offer`), Google/Apple sign-in, offline workouts (brief §3.4), app-side events,
  a developer reset menu, EAS internal builds.

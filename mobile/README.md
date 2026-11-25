# Lock In Mode – mobile app

React Native with Expo (SDK 58) and TypeScript. One codebase for Android and iOS.
Decisions: [ADR 0029](../docs/decisions/0029-mobile-app-foundation.md).

**What works so far:** first launch signs in as a guest by itself → onboarding (one question
per screen) → quick safety check → "Building your plan" with the real reasons → your plan
(weeks, shoulder day / bro split choices) → a preview of each workout. The workout player is
the next stage.

## Run it on your phone (Expo Go)

You need Node.js 22 (LTS) and the **Expo Go** app on the phone.

1. **Check Expo Go's SDK.** Open Expo Go → Settings (or the profile tab): it lists the
   supported SDK. This app is **SDK 58**. If your phone's Expo Go is older, install the SDK 58
   version from <https://expo.dev/go> (pick SDK 58, then your platform). Expo Go now asks you to
   sign in with a free Expo account.
2. **Install and configure** (from the repo root):
   ```bash
   cd mobile
   npm ci                      # exactly the locked packages (like `uv sync --locked`)
   cp .env.example .env        # then set EXPO_PUBLIC_API_URL (see below)
   npx expo start
   ```
3. **Open it:** scan the QR code in the terminal. Android: with Expo Go. iPhone: with the
   Camera app, which hands it to Expo Go. Phone and computer on the same Wi-Fi.
   - Office or public Wi-Fi often blocks phone↔computer traffic. Then use
     `npx expo start --tunnel`. The tunnel goes through Expo's relay, which needs you
     logged in once on the computer: `npx expo login` (the same free account as Expo Go),
     check with `npx expo whoami`.

### Which API?
`EXPO_PUBLIC_API_URL` in `mobile/.env`:
- **The hosted API** ([docs/deploy.md](../docs/deploy.md)):
  `https://lock-in-mode-api.vercel.app`. Works anywhere, phone data included. Easiest.
- **Your computer's API** (`docker compose up -d`): `http://<computer's LAN IP>:8000`
  (Linux: `hostname -I`, Windows: `ipconfig`). Never `localhost`: on the phone, that's the
  phone itself.

The value is baked in when the app is bundled: after changing it, stop `npx expo start`
and start it again.

### Start over as a new user
The sign-in is kept in the phone's secure storage. To test onboarding again:
- Android: Settings → Apps → Expo Go → Storage → Clear data (or uninstall the app).
- iPhone: the Keychain survives reinstalls, so deleting Expo Go isn't enough; for now use the
  other phone, or a fresh local database. (A developer "reset" menu comes later.)

Guests can't sign out yet on purpose: a guest who signs out can never come back, and the
server erases them within an hour (ADR 0027).

## Checks (the same run in CI)
```bash
npm run typecheck     # TypeScript, strict
npm run lint          # ESLint (expo config)
npm test              # Jest: unit tests + the first-run journey through the real screens
npm run check         # all three
```

Once, on a normal internet connection, confirm every package matches SDK 58 (the versions were
taken from Expo's SDK 58 template because Expo's version service wasn't reachable when this
was set up):
```bash
npx expo install --check
```

## Offline (ADR 0033)
Once the app has been online, it opens without a connection, and the next workout (kept
downloaded by the plan screen) can be started, trained and finished offline. Everything
done in a workout goes into the journal on the phone first and is sent from there,
online a moment later, offline once the phone is back, with the time each thing happened.
To try it: open the plan online once, switch on airplane mode, close and reopen the app,
do the workout, then switch airplane mode off: the plan shows what changed.

## When the API changes
The app's API types (`src/api/schema.d.ts`) are generated from the API's OpenAPI schema, so a
renamed field is a compile error here instead of a crash on a phone. After a backend change
to routes or schemas, with the API running locally:
```bash
npm run api:types     # rewrites src/api/schema.d.ts from http://localhost:8000/openapi.json
```
Commit it with the backend change. CI fails if they don't match.

## How it's built (for a .NET / Unity developer)

| Here | What it is | Like in .NET / Unity |
|---|---|---|
| `src/app/` (Expo Router) | Each file is a screen; `_layout.tsx` wraps them | Razor Pages folder routing; `_layout` ≈ `Program.cs` + `MainLayout` |
| Component (`function Plan() { return <View>… }`) | A function that returns what to draw; redraws when its props/state change | A prefab / Blazor component |
| `useState` | A value that survives redraws; setting it redraws | A field on a MonoBehaviour that triggers a refresh |
| `useEffect` | Code that runs after drawing (timers, subscriptions) and can clean up | `OnEnable` / `OnDisable` |
| TanStack Query (`useQuery`, `useMutation`) | Fetches and caches server data; tracks loading/error | A cached repository + `IsBusy` state |
| `src/api/client.ts` | One typed API client from the OpenAPI schema | An NSwag/Refit client from swagger.json |
| `src/api/auth.ts` | Adds the token, refreshes it, retries once | A `DelegatingHandler` on `HttpClient` |
| `src/api/tokens.ts` | Keychain/Keystore storage for the sign-in | DPAPI / `ProtectedData` |
| `src/features/` | Plain TypeScript rules (onboarding steps, labels) | Domain/service classes, unit-tested |
| `src/ui/kit.tsx` | The few shared building blocks | A UI prefab library |
| `src/state/player.ts` (`usePlayer`) | The workout player's state: next set, timers, sending ticks | A MonoBehaviour that owns the game state |
| `src/features/player/clock.ts` | Timers that store when they end | A `DateTime` deadline instead of `timer -= Time.deltaTime` |
| `useRef` | A value that survives redraws but doesn't trigger one | A private field that isn't serialized |
| `useKeepAwake`, `useAudioPlayer` | Keep the screen on; play a sound | `Screen.sleepTimeout = NeverSleep`; an `AudioSource` |
| The journal (`src/state/journal.tsx`) | The workout in progress, written on the phone first, sent after | An outbox table drained by a `BackgroundService` |
| `expo-sqlite/kv-store` | Small key-value storage on the phone (sync or async) | `PlayerPrefs` / a JSON file in `Application.persistentDataPath` |
| `PersistQueryClientProvider` | Saves the query cache on the phone, reads it back at launch | An offline cache of `HttpClient` responses on disk |
| `onlineManager` + `expo-network` | One app-wide "online?" flag that queries obey | `NetworkChange.NetworkAvailabilityChanged` |
| `useSyncExternalStore` | Redraw when something outside React changes | Subscribing to a C# `event` in `OnEnable` |

```
src/
├── app/                 screens (routes)
│   ├── _layout.tsx      providers + which screens are open right now
│   ├── index.tsx        "/": loading or "Hold on" with Try again
│   ├── onboarding.tsx   the quiz, one question per screen
│   ├── safety.tsx       four yes/no questions
│   ├── plan.tsx         reveal, the week, choices, Lock In button
│   └── workout/[id]/
│       ├── index.tsx    a workout's exercises, Start / Continue / Skip
│       └── play.tsx     the player → "How did that feel?" → what changed
├── api/                 client, auth, tokens, errors, every call (endpoints.ts)
├── features/            pure + tested: onboarding flow, plan labels, safety answers,
│   ├── player/          steps (screens and sets), entry (pre-fill), clock, words, result
│   └── offline/         journal (the workout on the phone) and sync (sending it)
├── state/
│   ├── startup.ts       "where should this person be?" → drives the navigator
│   ├── player.ts        the player's state and actions (usePlayer)
│   ├── journal.tsx      the journal store: saved at once, sent with retries
│   ├── online.ts        online or not (expo-network → TanStack's onlineManager)
│   ├── persist.ts       what's kept on the phone between launches, for 14 days
│   └── ready.ts         keeps the next workout downloaded
├── test/                fixtures, fakes of expo-sqlite's store and expo-network
└── ui/
    ├── kit.tsx          Screen, Title, Choice, LockInButton, Sheet, Stepper…
    ├── player.tsx       the player's screens (draws what usePlayer returns)
    └── alerts.ts        beep + buzz at the end of a rest or a timed move
assets/sounds/           tick.wav (3-2-1) and done.wav (made for this app)
```

**One rule drives navigation:** `src/state/startup.ts` works out a stage (loading, error,
offline, onboarding, safety, plan) from the sign-in and the profile. `_layout.tsx` opens only that
stage's screens (`Stack.Protected`). Saving onboarding updates the cached profile, the stage
becomes "safety", and Expo Router moves the person there. No screen navigates by hand
after a save.

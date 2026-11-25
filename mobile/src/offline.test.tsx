/**
 * Offline workouts (ADR 0033) through the REAL screens and navigator, with the API, the
 * phone's storage and the connection faked:
 *
 *   online once (the next workout downloads) -> app closed -> opens offline -> start,
 *   tick, finish -> "saved on this phone" -> back online -> sent with the phone's times
 *   -> what changed shows on the plan.
 *
 * Plus: closing the app mid-workout, a copy too old to start, the plan moving on while
 * offline, swaps needing a connection, and a first launch with no connection at all.
 */
import { dehydrate, notifyManager, onlineManager, QueryClient } from '@tanstack/react-query';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import type { Plan, Profile, Session, SessionResult } from '@/api/endpoints';
import * as endpoints from '@/api/endpoints';
import { ApiError } from '@/api/problem';
import { begin, record } from '@/features/offline/journal';
import { JOURNAL_KEY } from '@/state/journal';
import { CACHE_KEY, CACHE_VERSION, shouldKeep } from '@/state/persist';
import { keys } from '@/state/startup';
import { detail, row, workout } from '@/test/fixtures';
import { default as storage, resetStorage, storedItem } from '@/test/kv-store';
import { setConnected } from '@/test/network';

jest.mock('@/api/client', () => ({
  auth: { ensureSignedIn: jest.fn(async () => {}), forget: jest.fn(async () => {}) },
  api: {},
}));

jest.mock('@/api/endpoints', () => ({
  ...jest.requireActual('@/api/endpoints'),
  getProfileOrNull: jest.fn(),
  getOrCreatePlan: jest.fn(),
  getWorkout: jest.fn(),
  getOpenSessionOrNull: jest.fn(),
  startSession: jest.fn(),
  getExercise: jest.fn(),
  logSet: jest.fn(),
  deleteSet: jest.fn(),
  finishSession: jest.fn(),
  swapExercise: jest.fn(),
}));

const mockAlerts = { countIn: jest.fn(), done: jest.fn(), ticked: jest.fn() };
jest.mock('@/ui/alerts', () => ({ useAlerts: () => mockAlerts }));
jest.mock('expo-keep-awake', () => ({ useKeepAwake: jest.fn() }));

const api = jest.mocked(endpoints);
notifyManager.setScheduler((callback) => callback());

// A whole-app test does a lot: on a fresh checkout (CI) the first one also compiles every
// screen. Jest's default of 5 s per test is too tight on a busy machine.
jest.setTimeout(30_000);

const DAY = 24 * 60 * 60 * 1000;

const PROFILE = {
  goal: 'build_muscle',
  level: 'beginner',
  location: 'gym',
  equipment: [],
  limits: [],
  days_per_week: 3,
  minutes_per_session: 45,
  women_home_track: false,
  prefers_bro_split: false,
  shoulder_day: 'push',
  obstacles: [],
  needs_low_intensity: false,
  safety_screened_at: '2026-11-24T10:05:00Z',
  created_at: '2026-11-24T10:00:00Z',
  updated_at: '2026-11-24T10:00:00Z',
  bro_split_available: false,
} as Profile;

function plan(next: 'w1' | 'w2' = 'w1'): Plan {
  return {
    id: 'plan-1',
    block_number: 1,
    routine_kind: 'full_body',
    reasons: ['3 days a week: full body each time.'],
    weekdays: [0, 2, 4],
    uses_push_pull_legs: false,
    weeks: 5,
    created_at: '2026-11-24T10:00:00Z',
    next_workout_id: next,
    block_complete: false,
    comeback: null,
    level_up: null,
    workouts: [
      { id: 'w1', position: 1, week: 1, kind: 'full_body', title: 'Full body A', format: 'straight_sets', recovery: false, total_minutes: 30, status: next === 'w1' ? 'pending' : 'done', comeback_week: null },
      { id: 'w2', position: 2, week: 1, kind: 'full_body', title: 'Full body B', format: 'straight_sets', recovery: false, total_minutes: 30, status: 'pending', comeback_week: null },
    ],
  };
}

/** Main: push-up 2 sets, no rest (quick to tick through). */
const PUSH_UPS = workout({ main: [row('a', 'Push-up', { sets: 2, rest_seconds: 0 })] });

const offlineError = () => new TypeError('Network request failed');

/** The fake API answers only while the fake phone is online, like the real one. */
function online<T extends unknown[], R>(answer: (...args: T) => R | Promise<R>) {
  return async (...args: T): Promise<R> => {
    if (!onlineManager.isOnline()) throw offlineError();
    return answer(...args);
  };
}

function session(): Session {
  return { id: 's1', workout_id: 'w1', started_at: '2026-11-25T10:00:00Z', finished_at: null, feedback: null, sets: [] };
}

function result(): SessionResult {
  return {
    ...session(),
    finished_at: '2026-11-25T10:30:00Z',
    placements: [],
    progress: [{ exercise: { id: 'x-a', slug: 'a', name: 'Push-up', difficulty: 2 }, change: 'more_reps', weight_kg: null, seconds: null, set_change: 0 }],
    intervals: null,
    recovery_earned: false,
    next_workout_id: 'w2',
    block_complete: false,
    sign_in_offer: null,
  };
}

function setUp() {
  api.getProfileOrNull.mockImplementation(online(() => PROFILE));
  api.getOrCreatePlan.mockImplementation(online(() => ({ plan: plan(), justCreated: false })));
  api.getWorkout.mockImplementation(online((id: string) => (id === 'w1' ? PUSH_UPS : workout({ id: 'w2', position: 2 }))));
  api.getOpenSessionOrNull.mockImplementation(online(() => null));
  api.getExercise.mockImplementation(online((id: string) => detail(id)));
  api.startSession.mockImplementation(online(() => session()));
  api.logSet.mockImplementation(
    online((where: { plannedExerciseId: string; setNumber: number }) => ({
      planned_exercise_id: where.plannedExerciseId,
      set_number: where.setNumber,
      reps: 8,
      weight_kg: null,
      seconds: null,
    })),
  );
  api.finishSession.mockImplementation(online(() => result()));
}

beforeEach(() => {
  jest.clearAllMocks();
  resetStorage();
  setConnected(true);
  onlineManager.setOnline(true);
  setUp();
});

const tap = (target: string | RegExp | ReturnType<typeof screen.getByText>) =>
  fireEvent.press(typeof target === 'string' || target instanceof RegExp ? screen.getByText(target) : target);

async function wait(ms: number) {
  for (let waited = 0; waited < ms; waited += 50) {
    await act(async () => {
      await jest.advanceTimersByTimeAsync(50);
    });
  }
}

async function find(text: string | RegExp, withinMs = 1500) {
  for (let waited = 0; waited < withinMs; waited += 50) {
    const [element] = screen.queryAllByText(text);
    if (element) return element;
    await wait(50);
  }
  return screen.getByText(text);
}

async function goOffline() {
  await act(async () => setConnected(false));
}

async function goOnline() {
  await act(async () => setConnected(true));
}

/** What the phone saved the last time it was online (`daysAgo`): the profile, the plan,
 * workout 1 and its exercise. Written the way the app writes it (src/state/persist.ts). */
function savedOnPhone(daysAgo = 0) {
  const updatedAt = Date.now() - daysAgo * DAY;
  const client = new QueryClient();
  client.setQueryData(keys.profile, PROFILE, { updatedAt });
  client.setQueryData(keys.plan, { plan: plan(), justCreated: false }, { updatedAt });
  client.setQueryData(keys.openSession, null, { updatedAt });
  client.setQueryData(keys.workout('w1'), PUSH_UPS, { updatedAt });
  client.setQueryData(keys.exercise('x-a'), detail('x-a'), { updatedAt });
  const saved = { timestamp: Date.now(), buster: CACHE_VERSION, clientState: dehydrate(client, { shouldDehydrateQuery: shouldKeep }) };
  storage.setItemSync(CACHE_KEY, JSON.stringify(saved));
}

it('online, the plan screen downloads the next workout and saves it on the phone', async () => {
  await renderRouter('./src/app');
  expect(await find('Lock In: workout 1')).toBeOnTheScreen();
  await wait(1_500); // saving waits a second for more changes

  expect(api.getWorkout).toHaveBeenCalledWith('w1');
  expect(api.getExercise).toHaveBeenCalledWith('x-a');
  const saved = storedItem(CACHE_KEY) ?? '';
  expect(saved).toContain('"Push-up"');
  expect(saved).toContain('Start in position.'); // the exercise page, for "How to do it"
});

it('a whole workout offline: saved on the phone, sent once online, results on the plan', async () => {
  savedOnPhone();
  await goOffline();

  // Opens with no connection, from what the phone saved.
  await renderRouter('./src/app');
  expect(await find('Workout 1 is on this phone, ready to go.')).toBeOnTheScreen();
  expect(api.getOrCreatePlan).not.toHaveBeenCalled();

  await tap('Lock In: workout 1');
  await tap(await find('Lock In: start'));
  await tap(await find('✓ 8 reps'));
  await tap(await find('✓ 8 reps'));
  expect(await find('You’re offline: your workout saves on this phone and syncs when you’re back.')).toBeOnTheScreen();
  await tap('Just right');

  expect(await find('Saved on this phone')).toBeOnTheScreen();
  expect(api.startSession).not.toHaveBeenCalled();
  await tap('Lock In: done');
  expect(await find('Workout 1 · saved on this phone')).toBeOnTheScreen();
  expect(screen.getByText('Connect to get your next workout')).toBeOnTheScreen();

  // Back online: sent in order with the phone's times, then what changed shows.
  api.getOrCreatePlan.mockImplementation(online(() => ({ plan: plan('w2'), justCreated: false })));
  await goOnline();
  expect(await find('Done offline, synced just now.')).toBeOnTheScreen();
  expect(screen.getByText('Push-up: aim for 2 more reps next time')).toBeOnTheScreen();

  const startedAt = api.startSession.mock.calls[0]?.[1];
  expect(api.startSession).toHaveBeenCalledWith('w1', expect.any(String));
  expect(api.logSet).toHaveBeenCalledTimes(2);
  const firstSet = api.logSet.mock.calls[0]?.[1];
  expect(firstSet).toEqual({ reps: 8, weight_kg: null, seconds: null, logged_at: expect.any(String) });
  expect(Date.parse(firstSet?.logged_at ?? '')).toBeGreaterThanOrEqual(Date.parse(startedAt ?? ''));
  expect(api.finishSession).toHaveBeenCalledWith('s1', 'just_right', expect.any(String));

  await tap('Lock In: done');
  expect(await find('Lock In: workout 2')).toBeOnTheScreen();
});

it('closing the app mid-workout keeps every tick: it continues where it was', async () => {
  // The app was closed offline after the first set: the journal is on the phone.
  savedOnPhone();
  const now = new Date().toISOString();
  storage.setItemSync(JOURNAL_KEY, JSON.stringify(record(begin('w1', 1, now), 'a', 1, { reps: 8, weight_kg: null, seconds: null }, now)));
  await goOffline();

  await renderRouter('./src/app');
  await tap(await find('Lock In: continue workout 1'));
  expect(await find('Set 2 of 2')).toBeOnTheScreen();
  expect(screen.getByText('1 of 2 sets')).toBeOnTheScreen();
});

it('a copy older than 14 days can’t start offline: connect once', async () => {
  savedOnPhone(15);
  await goOffline();

  await renderRouter('./src/app');
  expect(await find('Connect once to get workout 1 ready')).toBeOnTheScreen();
});

it('the plan moved on while offline: says this workout couldn’t be saved', async () => {
  savedOnPhone();
  await goOffline();
  await renderRouter('./src/app');
  await tap(await find('Lock In: workout 1'));
  await tap(await find('Lock In: start'));
  await tap(await find('✓ 8 reps'));
  await tap(await find('More'));
  await tap('Finish workout now');
  await tap(await find('Skip'));
  await tap(await find('Lock In: done'));

  api.startSession.mockRejectedValue(new ApiError(409, 'not_next_workout'));
  await goOnline();

  expect(await find('Workout 1 couldn’t be saved')).toBeOnTheScreen();
  await tap('OK');
  expect(screen.queryByText('Workout 1 couldn’t be saved')).toBeNull();
});

it('swapping needs a connection; offline it says so instead', async () => {
  savedOnPhone();
  await goOffline();
  await renderRouter('./src/app');
  await tap(await find('Lock In: workout 1'));
  await tap(await find('Lock In: start'));
  await tap(await find('More'));

  expect(await find(/Swapping needs a connection/)).toBeOnTheScreen();
  expect(screen.queryByText('This hurts: swap it')).toBeNull();
});

it('online, a dropped connection mid-workout changes nothing: sets go when it’s back', async () => {
  await renderRouter('./src/app');
  await tap(await find('Lock In: workout 1'));
  await tap(await find('Lock In: start'));
  await find('✓ 8 reps');
  expect(api.startSession).toHaveBeenCalledTimes(1);

  await goOffline();
  await tap('✓ 8 reps');
  expect(await find('1 set is saved on this phone. It syncs when you’re online.')).toBeOnTheScreen();
  expect(api.logSet).not.toHaveBeenCalled();

  await goOnline();
  await wait(200);
  expect(api.logSet).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('1 set is saved on this phone. It syncs when you’re online.')).toBeNull();
});

it('the very first launch with no connection asks to connect once', async () => {
  await goOffline();
  await renderRouter('./src/app');
  expect(await find(/You’re offline. Connect once to set up Lock In Mode/)).toBeOnTheScreen();
});

/**
 * The whole first-run journey through the REAL screens and navigator (src/app), with the
 * API faked: start -> onboarding -> safety check -> "Building your plan" -> the plan ->
 * a workout preview. It checks the one thing unit tests can't: that unlocking a group
 * of screens (src/app/_layout.tsx) really moves the person to it.
 */
import { notifyManager, onlineManager } from '@tanstack/react-query';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import type { Plan, Profile, ProfileWrite, WorkoutDetail } from '@/api/endpoints';
import * as endpoints from '@/api/endpoints';
import { resetStorage } from '@/test/kv-store';
import { setConnected } from '@/test/network';

jest.mock('@/api/client', () => ({
  auth: { ensureSignedIn: jest.fn(async () => {}), forget: jest.fn(async () => {}) },
  api: {},
}));

jest.mock('@/api/endpoints', () => ({
  ...jest.requireActual('@/api/endpoints'),
  getProfileOrNull: jest.fn(),
  saveProfile: jest.fn(),
  saveDisplayName: jest.fn(async () => {}),
  submitSafetyScreen: jest.fn(),
  getOrCreatePlan: jest.fn(),
  getWorkout: jest.fn(),
}));

const api = jest.mocked(endpoints);

// renderRouter switches Jest to fake timers. TanStack Query hands results to screens
// with setTimeout(0), which fake timers would hold back: deliver them at once instead.
notifyManager.setScheduler((callback) => callback());

// What the phone saved (the cache, the journal) starts empty, and the phone online.
beforeEach(() => {
  resetStorage();
  setConnected(true);
  onlineManager.setOnline(true);
});

function profile(overrides: Partial<Profile> = {}): Profile {
  return {
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
    safety_screened_at: null,
    created_at: '2026-11-24T10:00:00Z',
    updated_at: '2026-11-24T10:00:00Z',
    bro_split_available: false,
    ...overrides,
  };
}

const PLAN: Plan = {
  id: 'plan-1',
  block_number: 1,
  routine_kind: 'full_body',
  reasons: ['3 days a week: full body each time.', 'Knees: no jumping.'],
  weekdays: [0, 2, 4],
  uses_push_pull_legs: false,
  weeks: 5,
  created_at: '2026-11-24T10:00:00Z',
  next_workout_id: 'w1',
  block_complete: false,
  comeback: null,
  level_up: null,
  workouts: [
    { id: 'w1', position: 1, week: 1, kind: 'full_body', title: 'Full body A', format: 'straight_sets', recovery: false, total_minutes: 45, status: 'pending', comeback_week: null },
    { id: 'w2', position: 2, week: 1, kind: 'full_body', title: 'Full body B', format: 'straight_sets', recovery: false, total_minutes: 45, status: 'pending', comeback_week: null },
  ],
};

const WORKOUT = {
  id: 'w1',
  position: 1,
  week: 1,
  title: 'Full body A',
  total_minutes: 45,
  recovery: false,
  warm_up: [],
  main: [
    {
      id: 'pe1',
      exercise: { id: 'x1', slug: 'push-up', name: 'Push-up', difficulty: 3 },
      sets: 1,
      reps_min: null,
      reps_max: null,
      seconds: null,
      rest_seconds: 90,
      reps_in_reserve: null,
      effort: null,
      group: 1,
      practice_sets: 0,
      is_test: true,
      swapped_out: false,
      weight_kg: null,
      last: null,
    },
  ],
  finisher: [],
  cool_down: [],
} as unknown as WorkoutDetail;

beforeEach(() => {
  jest.clearAllMocks();
});

/** Tap the element showing `text` (events are async in this testing library). */
const tap = (text: string | RegExp) => fireEvent.press(screen.getByText(text));

/** Let fake time move on, 50 ms at a time (up to `withinMs`), until `text` is on screen.
 * Small steps let React draw between timers, like on a phone. */
async function find(text: string | RegExp, withinMs = 1000) {
  for (let waited = 0; waited < withinMs; waited += 50) {
    const element = screen.queryByText(text);
    if (element) return element;
    await act(async () => {
      await jest.advanceTimersByTimeAsync(50);
    });
  }
  return screen.getByText(text); // not there: fails with the screen's contents
}

it('takes a new person from the first launch to their plan', async () => {
  api.getProfileOrNull.mockResolvedValue(null);
  api.saveProfile.mockImplementation(async (body: ProfileWrite) => profile({ ...body }));
  api.submitSafetyScreen.mockResolvedValue(profile({ safety_screened_at: '2026-11-24T10:05:00Z' }));
  api.getOrCreatePlan.mockResolvedValue({ plan: PLAN, justCreated: true });
  api.getWorkout.mockResolvedValue(WORKOUT);

  const router = await renderRouter('./src/app');

  // Onboarding, one question per screen.
  expect(await find("You're the main character.")).toBeOnTheScreen();
  await fireEvent.changeText(screen.getByLabelText('Your name, optional'), 'Shawaiz');
  await tap('Lock In');
  await tap('Build muscle'); // single choices move on by themselves
  expect(await find(/every part of each muscle/)).toBeOnTheScreen();
  await tap('Lock In');
  await tap('Never, on and off, or under 6 months');
  await tap('Gym'); // no equipment question at the gym
  await tap('3 days');
  await tap('45 min');
  await tap('Knees');
  await tap('Lock In');
  await tap('Skip'); // "What's made it hard before?" is optional

  // Saved in one PUT, then the name; the app moves to the safety check by itself.
  expect(await find('Quick safety check')).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/safety');
  expect(api.saveProfile).toHaveBeenCalledWith({
    goal: 'build_muscle',
    level: 'beginner',
    location: 'gym',
    equipment: [],
    women_home_track: false,
    days_per_week: 3,
    minutes_per_session: 45,
    limits: ['knees'],
    obstacles: [],
  });
  expect(api.saveDisplayName).toHaveBeenCalledWith('Shawaiz');

  // Safety check: all four must be answered.
  for (const no of screen.getAllByText('No')) await fireEvent.press(no);
  await tap('Lock In');

  // The plan is built and its real reasons appear one by one.
  expect(await find('Building your plan')).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/plan');
  expect(screen.queryByText('Knees: no jumping.')).toBeNull(); // not all at once
  expect(await find('Knees: no jumping.', 700 * PLAN.reasons.length + 500)).toBeOnTheScreen();
  await tap('Lock In: see my plan');

  // The week, and one big button for the next workout.
  expect(await find('Full body')).toBeOnTheScreen();
  expect(screen.getByText('Full body B')).toBeOnTheScreen();
  await tap('Lock In: workout 1');
  expect(await find('Push-up')).toBeOnTheScreen();
  expect(screen.getByText(/as many good reps as you can/)).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/workout/w1');
});

it('opens straight on the safety check when onboarding was done but not the check', async () => {
  api.getProfileOrNull.mockResolvedValue(profile());

  const router = await renderRouter('./src/app');

  expect(await find('Quick safety check')).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/safety');
});

it('opens straight on the plan for someone who finished everything', async () => {
  api.getProfileOrNull.mockResolvedValue(profile({ safety_screened_at: '2026-11-24T10:05:00Z' }));
  api.getOrCreatePlan.mockResolvedValue({ plan: PLAN, justCreated: false });

  const router = await renderRouter('./src/app');

  expect(await find('Full body A')).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/plan');
});

it('keeps people out of screens they are not ready for', async () => {
  api.getProfileOrNull.mockResolvedValue(null);

  const router = await renderRouter('./src/app', { initialUrl: '/plan' });

  expect(await find("You're the main character.")).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/onboarding');
});

it('shows what went wrong and tries again', async () => {
  api.getProfileOrNull
    .mockRejectedValueOnce(new TypeError('Network request failed'))
    .mockRejectedValueOnce(new TypeError('Network request failed'))
    .mockRejectedValueOnce(new TypeError('Network request failed'))
    .mockResolvedValue(null);

  await renderRouter('./src/app');
  // Two automatic retries first (src/state/startup.ts), then the error screen.
  await act(async () => {
    await jest.runAllTimersAsync();
  });
  expect(await find(/Can't reach Lock In Mode/)).toBeOnTheScreen();

  await tap('Try again');

  expect(await find("You're the main character.")).toBeOnTheScreen();
});

/**
 * The redesign's new parts (ADR 0036) through the REAL screens, with the API faked:
 *
 *   Home: the world card speaks the next step, the "new bests" tile, the muscle map
 *   (front and back), and its sheet with every head.
 *   Settings: the name, the beep and vibration switches (this phone), "Share usage data",
 *   "Download my data" (a file offered to the share sheet), and "Delete account", which
 *   ends with this phone starting again as a brand-new guest.
 */
import { notifyManager, onlineManager } from '@tanstack/react-query';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import { auth } from '@/api/client';
import type { Me, Muscles, Plan, Profile, Week } from '@/api/endpoints';
import * as endpoints from '@/api/endpoints';
import { ApiError } from '@/api/problem';
import { FEEL_KEY, forgetFeel, getFeel } from '@/state/feel';
import { deviceTimeZone } from '@/state/reminders';
import { resetFiles, shared, written } from '@/test/files';
import { resetStorage, storedItem } from '@/test/kv-store';
import { setConnected } from '@/test/network';
import { resetNotifications } from '@/test/notifications';

jest.mock('@/api/client', () => ({
  auth: {
    ensureSignedIn: jest.fn(async () => false),
    forget: jest.fn(async () => {}),
    onSignedOut: jest.fn(() => () => {}),
  },
  api: {},
}));

jest.mock('@/api/endpoints', () => ({
  ...jest.requireActual('@/api/endpoints'),
  getProfileOrNull: jest.fn(),
  getOrCreatePlan: jest.fn(),
  getOpenSessionOrNull: jest.fn(),
  getMe: jest.fn(),
  updateMe: jest.fn(),
  getWeek: jest.fn(),
  getXp: jest.fn(),
  getMuscles: jest.fn(),
  getBestsTotal: jest.fn(),
  saveDisplayName: jest.fn(),
  exportMyData: jest.fn(),
  deleteAccount: jest.fn(),
}));
jest.mock('@/ui/alerts', () => ({
  useAlerts: () => ({ countIn: jest.fn(), done: jest.fn(), ticked: jest.fn() }),
  useSoundCheck: () => ({ loaded: true, playing: false, play: jest.fn() }),
}));

const api = jest.mocked(endpoints);
notifyManager.setScheduler((callback) => callback());
jest.setTimeout(30_000);

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
  pact_signed_at: '2026-11-24T10:06:00Z',
  pact_due: false,
  created_at: '2026-11-24T10:00:00Z',
  updated_at: '2026-11-24T10:00:00Z',
  bro_split_available: false,
} as Profile;

const PLAN: Plan = {
  id: 'plan-1',
  block_number: 1,
  routine_kind: 'full_body',
  reasons: ['3 days a week: full body each time.'],
  weekdays: [0, 2, 4],
  uses_push_pull_legs: false,
  weeks: 5,
  created_at: '2026-11-24T10:00:00Z',
  next_workout_id: 'w1',
  block_complete: false,
  comeback: null,
  level_up: null,
  workouts: [
    { id: 'w1', position: 1, week: 1, kind: 'full_body', title: 'Pull', format: 'straight_sets', recovery: false, total_minutes: 45, status: 'pending', comeback_week: null },
  ],
};

const WEEK: Week = {
  week_start: '2026-11-23',
  done: 1,
  planned: 3,
  keep_at: 2,
  kept: false,
  streak: 4,
  best_streak: 4,
  freezes: 0,
  last_week: 'kept',
};

/** Chest and shoulders trained this week; back and biceps next. */
const MUSCLES = {
  week_start: '2026-11-23',
  next_workout: 'Pull',
  groups: [
    {
      group: 'chest',
      sets: 6,
      next_up: false,
      heads: [
        { head: 'chest_upper', sets: 3, next_up: false },
        { head: 'chest_mid', sets: 6, next_up: false },
        { head: 'chest_lower', sets: 0, next_up: false },
      ],
    },
    {
      group: 'back',
      sets: 0,
      next_up: true,
      heads: [
        { head: 'lats', sets: 0, next_up: true },
        { head: 'mid_back', sets: 0, next_up: true },
        { head: 'spinal_erectors', sets: 0, next_up: false },
      ],
    },
    {
      group: 'shoulders',
      sets: 1,
      next_up: false,
      heads: [
        { head: 'delt_front', sets: 1, next_up: false },
        { head: 'delt_side', sets: 0, next_up: false },
        { head: 'delt_rear', sets: 0, next_up: false },
      ],
    },
    {
      group: 'biceps',
      sets: 0,
      next_up: true,
      heads: [
        { head: 'biceps_long', sets: 0, next_up: true },
        { head: 'biceps_short', sets: 0, next_up: true },
        { head: 'brachialis', sets: 0, next_up: false },
      ],
    },
  ],
} as Muscles;

function me(overrides: Partial<Me> = {}): Me {
  return {
    id: 'u1',
    is_guest: true,
    display_name: null,
    created_at: '2026-11-24T10:00:00Z',
    share_usage_data: true,
    time_zone: deviceTimeZone(),
    reminder: null,
    progress_summary: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(auth.ensureSignedIn).mockResolvedValue(false);
  resetStorage();
  forgetFeel();
  resetFiles();
  resetNotifications();
  setConnected(true);
  onlineManager.setOnline(true);
  api.getProfileOrNull.mockResolvedValue(PROFILE);
  api.getOrCreatePlan.mockResolvedValue({ plan: PLAN, justCreated: false });
  api.getOpenSessionOrNull.mockResolvedValue(null);
  api.getMe.mockResolvedValue(me());
  api.updateMe.mockImplementation(async (changes) => ({ ...me(), ...changes }) as Me);
  api.getWeek.mockResolvedValue(WEEK);
  api.getXp.mockResolvedValue({ total: 380, level: 4, xp_into: 80, xp_needed: 400 });
  api.getMuscles.mockResolvedValue(MUSCLES);
  api.getBestsTotal.mockResolvedValue(9);
  api.saveDisplayName.mockResolvedValue(undefined);
  api.exportMyData.mockResolvedValue({ account: { id: 'u1' } });
  api.deleteAccount.mockResolvedValue(undefined);
});

const tap = (target: string | RegExp | ReturnType<typeof screen.getByText>) =>
  fireEvent.press(typeof target === 'string' || target instanceof RegExp ? screen.getByText(target) : target);

async function wait(ms: number) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
}

async function find(text: string | RegExp, withinMs = 1500) {
  for (let waited = 0; waited < withinMs; waited += 50) {
    const [element] = screen.queryAllByText(text);
    if (element) return element;
    await wait(50);
  }
  return screen.getByText(text);
}

async function findLabel(label: string | RegExp, withinMs = 1500) {
  for (let waited = 0; waited < withinMs; waited += 50) {
    const [element] = screen.queryAllByLabelText(label);
    if (element) return element;
    await wait(50);
  }
  return screen.getByLabelText(label);
}

async function openSettings() {
  await renderRouter('./src/app');
  await fireEvent.press(await findLabel('Settings'));
  expect(await find('Sound and feel')).toBeOnTheScreen();
}

// --- Home ----------------------------------------------------------------------------------

it('Home: the world speaks the next step, the streak runs along it, the bests tile counts', async () => {
  await renderRouter('./src/app');

  expect(await find('1 more this week?')).toBeOnTheScreen();
  expect(screen.getByText('4-week streak. 1 more workout keeps it going.')).toBeOnTheScreen();
  expect(screen.getByLabelText('1 of 3 workouts')).toBeOnTheScreen();
  expect(await findLabel('9 new bests')).toBeOnTheScreen();
  expect(screen.getByText('Lock In: workout 1')).toBeOnTheScreen();
  expect(screen.getByText('Pull · about 45 min')).toBeOnTheScreen();
});

it('Home: the muscle map says what was trained and what’s next, and shows every head', async () => {
  await renderRouter('./src/app');

  expect(await find('Chest, shoulders')).toBeOnTheScreen();
  expect(screen.getByText('Next up: back, biceps')).toBeOnTheScreen();
  await fireEvent.press(
    screen.getByLabelText('Muscles this week: Chest, shoulders. Next up: back, biceps.'),
  );

  expect(await find('Sets that trained each muscle since Monday. Warm-ups don’t count.')).toBeOnTheScreen();
  expect(screen.getAllByText('6 sets')).toHaveLength(2); // chest, and its mid head
  expect(screen.getByText('Upper chest')).toBeOnTheScreen();
  expect(screen.getByText('Rear delts')).toBeOnTheScreen(); // every head, trained or not
  expect(screen.getByText('Long head (outer)')).toBeOnTheScreen();
  expect(screen.getAllByText('Next up')).toHaveLength(2); // back and biceps
});

it('Home: before the first workout of the week, nothing is trained yet', async () => {
  api.getWeek.mockResolvedValue({ ...WEEK, done: 0, streak: 0 });
  api.getMuscles.mockResolvedValue({
    ...MUSCLES,
    groups: MUSCLES.groups.map((g) => ({ ...g, sets: 0, heads: g.heads.map((h) => ({ ...h, sets: 0 })) })),
  });
  api.getBestsTotal.mockResolvedValue(1);
  await renderRouter('./src/app');

  expect(await find('Ready when you are.')).toBeOnTheScreen();
  expect(await find('Nothing yet this week')).toBeOnTheScreen();
  expect(await findLabel('1 new best')).toBeOnTheScreen();
});

// --- Settings ------------------------------------------------------------------------------

it('Settings: the beep and vibration switches are this phone’s, and stay switched', async () => {
  await openSettings();

  await fireEvent(screen.getByLabelText('Rest beep'), 'valueChange', false);
  expect(getFeel()).toEqual({ beep: false, vibration: true });
  await fireEvent(screen.getByLabelText('Vibration'), 'valueChange', false);

  expect(JSON.parse(storedItem(FEEL_KEY) ?? '{}')).toEqual({ beep: false, vibration: false });
  forgetFeel(); // the app opened again: read back from the phone
  expect(getFeel()).toEqual({ beep: false, vibration: false });
  expect(api.updateMe).not.toHaveBeenCalled(); // nothing sent to the account
});

it('Settings: "Share usage data" off is saved on the account', async () => {
  await openSettings();

  await fireEvent(screen.getByLabelText('Share usage data'), 'valueChange', false);
  await wait(100);

  expect(api.updateMe).toHaveBeenCalledWith({ share_usage_data: false });
  expect(screen.getByLabelText('Share usage data')).toHaveProp('value', false);
});

it('Settings: the name is optional and tidied', async () => {
  await openSettings();
  await tap('Your name');
  await fireEvent.changeText(await findLabel('Your name'), '  Shawaiz ');
  await tap('Save');
  await wait(100);

  expect(api.saveDisplayName).toHaveBeenCalledWith('Shawaiz');
});

it('Settings: "Download my data" writes one file and offers it to the share sheet', async () => {
  await openSettings();
  await tap('Download my data');
  await wait(100);

  expect(api.exportMyData).toHaveBeenCalledTimes(1);
  expect(JSON.parse(written.get('file:///cache/lock-in-mode-data.json') ?? '{}')).toEqual({
    account: { id: 'u1' },
  });
  expect(shared).toEqual([
    {
      uri: 'file:///cache/lock-in-mode-data.json',
      options: expect.objectContaining({ mimeType: 'application/json' }),
    },
  ]);
});

it('Settings: a phone that can’t share files says so instead of failing quietly', async () => {
  resetFiles(false);
  await openSettings();
  await tap('Download my data');

  expect(await find('This phone can’t share files. Try again on another phone.')).toBeOnTheScreen();
  expect(shared).toEqual([]);
});

it('Settings: a 4th download in an hour says to wait', async () => {
  api.exportMyData.mockRejectedValue(
    new ApiError(429, 'rate_limited'),
  );
  await openSettings();
  await tap('Download my data');

  expect(await find('That’s 3 downloads this hour. Try again in a little while.')).toBeOnTheScreen();
  expect(shared).toEqual([]);
});

it('Settings: deleting asks first, sends the optional reason, then starts a fresh guest', async () => {
  await openSettings();
  await tap('Delete account');

  expect(await find('Delete your account?')).toBeOnTheScreen();
  expect(api.deleteAccount).not.toHaveBeenCalled(); // asks first
  await tap('No time');

  // The server erased it: this phone starts again as a brand-new guest.
  jest.mocked(auth.ensureSignedIn).mockResolvedValue(true);
  api.getProfileOrNull.mockResolvedValue(null);
  await tap('Delete for good');

  expect(await find('What’s your goal?')).toBeOnTheScreen();
  expect(api.deleteAccount.mock.calls[0]?.[0]).toBe('no_time');
  expect(auth.forget).toHaveBeenCalled();
});

it('Settings: "Keep my account" closes without deleting', async () => {
  await openSettings();
  await tap('Delete account');
  await tap(await find('Keep my account'));
  await wait(100);

  expect(api.deleteAccount).not.toHaveBeenCalled();
  expect(screen.getByText('Sound and feel')).toBeOnTheScreen();
});

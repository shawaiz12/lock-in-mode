/**
 * The weekly ring, new bests and the reminder (ADR 0034) through the REAL screens, with
 * the API, notifications and storage faked:
 *
 *   Home shows "This week ●○○ 1 of 3" and the streak -> workout 1's finish screen shows
 *   the new best, the kept week and a reminder offer -> "Remind me" asks permission,
 *   schedules one reminder per training day and saves it on the account.
 *
 * Plus: permission refused, changing and turning off the reminder on Home, the phone's
 * time zone sent to the account, a saved reminder set up again on a new phone, and the
 * sound check.
 */
import { notifyManager, onlineManager } from '@tanstack/react-query';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';
import { AccessibilityInfo } from 'react-native';

import type { Me, Plan, Profile, Session, SessionResult, Week } from '@/api/endpoints';
import * as endpoints from '@/api/endpoints';
import { deviceTimeZone } from '@/state/reminders';
import { detail, row, workout } from '@/test/fixtures';
import { resetStorage } from '@/test/kv-store';
import { notificationAsync } from '@/test/haptics';
import { setConnected } from '@/test/network';
import { asked, resetNotifications, scheduled } from '@/test/notifications';

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
  getWorkout: jest.fn(),
  getOpenSessionOrNull: jest.fn(),
  startSession: jest.fn(),
  getExercise: jest.fn(),
  logSet: jest.fn(),
  deleteSet: jest.fn(),
  finishSession: jest.fn(),
  getMe: jest.fn(),
  updateMe: jest.fn(),
  getWeek: jest.fn(),
  getXp: jest.fn(),
}));

const mockAlerts = { countIn: jest.fn(), done: jest.fn(), ticked: jest.fn() };
jest.mock('@/ui/alerts', () => ({
  useAlerts: () => mockAlerts,
  useSoundCheck: () => ({ loaded: true, playing: false, play: mockAlerts.done }),
}));
jest.mock('expo-keep-awake', () => ({ useKeepAwake: jest.fn() }));

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
    { id: 'w1', position: 1, week: 1, kind: 'full_body', title: 'Full body A', format: 'straight_sets', recovery: false, total_minutes: 30, status: 'pending', comeback_week: null },
  ],
};

const WEEK: Week = {
  week_start: '2026-11-23',
  done: 1,
  planned: 3,
  keep_at: 2,
  kept: false,
  streak: 2,
  best_streak: 2,
  freezes: 1,
  last_week: 'kept',
};

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

function session(): Session {
  return { id: 's1', workout_id: 'w1', started_at: '2026-11-25T10:00:00Z', finished_at: null, feedback: null, sets: [] };
}

function result(overrides: Partial<SessionResult> = {}): SessionResult {
  return {
    ...session(),
    finished_at: '2026-11-25T10:30:00Z',
    placements: [],
    progress: [],
    intervals: null,
    recovery_earned: false,
    next_workout_id: 'w2',
    block_complete: false,
    sign_in_offer: null,
    new_bests: [],
    week: { ...WEEK, done: 2, kept: true, streak: 3 },
    offer_reminder: false,
    ...overrides,
  };
}

function setUp(account: Me = me()) {
  api.getProfileOrNull.mockResolvedValue(PROFILE);
  api.getOrCreatePlan.mockResolvedValue({ plan: PLAN, justCreated: false });
  api.getWorkout.mockResolvedValue(workout({ main: [row('a', 'Push-up', { sets: 1, rest_seconds: 0 })] }));
  api.getOpenSessionOrNull.mockResolvedValue(null);
  api.startSession.mockResolvedValue(session());
  api.getExercise.mockImplementation(async (id: string) => detail(id));
  api.logSet.mockImplementation(async (where) => ({
    planned_exercise_id: where.plannedExerciseId,
    set_number: where.setNumber,
    reps: 8,
    weight_kg: null,
    seconds: null,
  }));
  api.finishSession.mockResolvedValue(result());
  api.getMe.mockResolvedValue(account);
  api.updateMe.mockImplementation(async (changes) => ({ ...account, ...changes }) as Me);
  api.getWeek.mockResolvedValue(WEEK);
  api.getXp.mockResolvedValue({ total: 1320, level: 7, xp_into: 320, xp_needed: 1000 });
}

beforeEach(() => {
  jest.clearAllMocks();
  resetStorage();
  resetNotifications();
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

/** Open the app, do workout 1 (one set), tap "Just right". */
async function finishWorkoutOne() {
  await renderRouter('./src/app');
  await tap(await find('Lock In: workout 1'));
  await tap(await find('Lock In: start'));
  await tap(await find('✓ 8 reps'));
  await tap(await find('Just right'));
}

it('Home shows this week and the streak, in weeks', async () => {
  await renderRouter('./src/app');

  expect(await find('This week')).toBeOnTheScreen();
  expect(screen.getByText('1 of 3 workouts')).toBeOnTheScreen();
  expect(screen.getByLabelText('1 of 3 workouts')).toBeOnTheScreen();
  expect(screen.getByText('2-week streak. 1 more workout keeps it going.')).toBeOnTheScreen();
  expect(screen.getByText('1 freeze ready: it saves a week you miss.')).toBeOnTheScreen();
});

it('the finish screen leads with a new best and says the week counts', async () => {
  api.finishSession.mockResolvedValue(
    result({
      new_bests: [{ exercise: { id: 'x-a', slug: 'push-up', name: 'Push-up', difficulty: 2 }, kind: 'reps', value: 14, previous: 12 }],
      week: { ...WEEK, done: 2, kept: true, streak: 3 },
    }),
  );
  await finishWorkoutOne();

  expect(await find('Real progress')).toBeOnTheScreen();
  expect(screen.getByText('New best: 14 reps of Push-up')).toBeOnTheScreen();
  expect(await find('This week counts: 3-week streak.')).toBeOnTheScreen(); // a beat later
  expect(screen.queryByText('Make it a habit')).toBeNull(); // not offered this time
});

it('workout 1 offers a reminder on the plan’s days at the time just trained, one tap', async () => {
  api.finishSession.mockResolvedValue(result({ offer_reminder: true }));
  await finishWorkoutOne();

  expect(await find('Make it a habit')).toBeOnTheScreen();
  expect(screen.getByText(/^Mon, Wed, Fri at \d\d:\d\d$/)).toBeOnTheScreen();
  await tap('Remind me');

  expect(await find('Reminder on')).toBeOnTheScreen();
  expect(asked.count).toBe(1); // asked right after the win, not before
  expect(scheduled.map((s) => s.trigger.weekday)).toEqual([2, 4, 6]); // Mon, Wed, Fri
  expect(scheduled[0]?.trigger).toMatchObject({ type: 'weekly', channelId: 'reminders' });
  expect(api.updateMe).toHaveBeenCalledWith({
    reminder: { at: expect.stringMatching(/^\d\d:[03]0:00$/), days: [0, 2, 4] },
  });
});

it('notifications refused: says how to turn them on, saves nothing', async () => {
  resetNotifications({ willAllow: false });
  api.finishSession.mockResolvedValue(result({ offer_reminder: true }));
  await finishWorkoutOne();
  await tap(await find('Remind me'));

  expect(await find(/Notifications are off for Lock In Mode/)).toBeOnTheScreen();
  expect(scheduled).toHaveLength(0);
  expect(api.updateMe).not.toHaveBeenCalledWith(expect.objectContaining({ reminder: expect.anything() }));
});

it('"Not now" just closes the offer', async () => {
  api.finishSession.mockResolvedValue(result({ offer_reminder: true }));
  await finishWorkoutOne();
  await tap(await find('Not now'));

  expect(screen.queryByText('Make it a habit')).toBeNull();
  expect(asked.count).toBe(0);
});

it('Home: change the reminder’s time, then turn it off', async () => {
  resetNotifications({ granted: true });
  setUp(me({ reminder: { at: '07:00:00', days: [1, 3] } }));
  await renderRouter('./src/app');

  expect(await find('Tue, Thu at 07:00')).toBeOnTheScreen();
  await tap('Change the reminder');
  await tap(await find('+30 min'));
  await tap('Save reminder');
  await wait(100);

  expect(api.updateMe).toHaveBeenCalledWith({ reminder: { at: '07:30:00', days: [1, 3] } });
  expect(scheduled.map((s) => [s.trigger.weekday, s.trigger.hour, s.trigger.minute])).toEqual([
    [3, 7, 30],
    [5, 7, 30],
  ]);

  await tap(await find('Change the reminder'));
  await tap(await find('Turn the reminder off'));
  await wait(100);
  expect(api.updateMe).toHaveBeenLastCalledWith({ reminder: null });
  expect(scheduled).toHaveLength(0);
});

it('a saved reminder is set up again on a new phone', async () => {
  resetNotifications({ granted: true });
  setUp(me({ reminder: { at: '18:00:00', days: [0, 2, 4] } }));
  await renderRouter('./src/app');
  await find('Mon, Wed, Fri at 18:00');
  await wait(100);

  expect(scheduled.map((s) => s.trigger.weekday)).toEqual([2, 4, 6]);
  expect(asked.count).toBe(0); // never asks by itself
});

it('sends the phone’s time zone to the account when it differs', async () => {
  setUp(me({ time_zone: null }));
  await renderRouter('./src/app');
  await find('This week');
  await wait(100);

  expect(api.updateMe).toHaveBeenCalledWith({ time_zone: deviceTimeZone() });
});

it('the sound check plays the beep and explains the media volume', async () => {
  await renderRouter('./src/app');
  await tap(await find('Sound check'));

  expect(await find('Sound ready.')).toBeOnTheScreen();
  await tap('Play the beep');
  expect(mockAlerts.done).toHaveBeenCalled();
  expect(await find(/uses the media volume, not the ringer/)).toBeOnTheScreen();
});

it('a saved reminder without permission on this phone: never asks by itself', async () => {
  resetNotifications({ granted: false });
  setUp(me({ reminder: { at: '18:00:00', days: [0, 2, 4] } }));
  await renderRouter('./src/app');
  await find('Mon, Wed, Fri at 18:00');
  await wait(100);

  expect(asked.count).toBe(0);
  expect(scheduled).toHaveLength(0);
});

it('after a hard "don’t ask again", it doesn’t ask: it says where to turn them on', async () => {
  resetNotifications({ granted: false, canAskAgain: false });
  api.finishSession.mockResolvedValue(result({ offer_reminder: true }));
  await finishWorkoutOne();
  await tap(await find('Remind me'));

  expect(await find(/Notifications are off for Lock In Mode/)).toBeOnTheScreen();
  expect(asked.count).toBe(0);
});


// --- XP and the Lock In level (ADR 0035) ---------------------------------------------------

const LEVEL = (level: number, into: number, needed: number) => ({
  total: into,
  level,
  xp_into: into,
  xp_needed: needed,
});

it('Home shows the Lock In level under the week', async () => {
  await renderRouter('./src/app');
  expect(await find('Lock In level 7 · 320 / 1,000 XP')).toBeOnTheScreen();
});

it('the finish screen reveals XP after the real progress: count-up, items, level-up', async () => {
  api.finishSession.mockResolvedValue(
    result({
      new_bests: [{ exercise: { id: 'x-a', slug: 'push-up', name: 'Push-up', difficulty: 2 }, kind: 'reps', value: 14, previous: 12 }],
      xp: {
        items: [
          { source: 'workout', amount: 100 },
          { source: 'best', amount: 25 },
          { source: 'week', amount: 150 },
        ],
        gained: 275,
        bonus: false,
        capped: false,
        before: LEVEL(2, 150, 200),
        after: LEVEL(3, 125, 300),
      },
    }),
  );
  await finishWorkoutOne();

  expect(await find('Real progress')).toBeOnTheScreen();
  expect(screen.queryByText('Workout +100')).toBeNull(); // not yet: real progress first
  expect(await find('+275 XP', 3000)).toBeOnTheScreen(); // counted up
  expect(screen.getByText('Workout +100')).toBeOnTheScreen();
  expect(screen.getByText('New bests +25')).toBeOnTheScreen();
  expect(screen.getByText('Week kept +150')).toBeOnTheScreen();
  expect(await find('Lock In level 3!', 3000)).toBeOnTheScreen();
  expect(screen.getByText('Lock In level 3 · 125 / 300 XP')).toBeOnTheScreen();
  expect(notificationAsync).toHaveBeenCalledTimes(1); // the level-up buzz
});

it('XP without a level-up: the bar moves, no celebration', async () => {
  api.finishSession.mockResolvedValue(
    result({
      xp: { items: [{ source: 'workout', amount: 100 }], gained: 100, bonus: false, capped: false, before: LEVEL(3, 0, 300), after: LEVEL(3, 100, 300) },
    }),
  );
  await finishWorkoutOne();

  expect(await find('Lock In level 3 · 100 / 300 XP', 3000)).toBeOnTheScreen();
  expect(screen.queryByText(/!$/)).toBeNull();
  expect(notificationAsync).not.toHaveBeenCalled();
});

it('past the week’s XP limit: a calm line instead of XP', async () => {
  api.finishSession.mockResolvedValue(
    result({
      xp: { items: [], gained: 0, bonus: false, capped: true, before: LEVEL(4, 10, 400), after: LEVEL(4, 10, 400) },
    }),
  );
  await finishWorkoutOne();

  expect(await find('Rest counts too: you’ve done your week.', 3000)).toBeOnTheScreen();
  expect(screen.queryByText(/XP$/)).toBeNull();
});

it('with "reduce motion" on, everything shows at once', async () => {
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(true);
  api.finishSession.mockResolvedValue(
    result({
      xp: { items: [{ source: 'workout', amount: 100 }], gained: 100, bonus: false, capped: false, before: LEVEL(1, 0, 100), after: LEVEL(2, 0, 200) },
    }),
  );
  await finishWorkoutOne();

  expect(await find('Locked in.')).toBeOnTheScreen();
  await wait(50);
  expect(screen.getByText('+100 XP')).toBeOnTheScreen();
  expect(screen.getByText('Lock In level 2!')).toBeOnTheScreen();
});

it('a finish that adds no XP (already counted) shows no XP card', async () => {
  api.finishSession.mockResolvedValue(
    result({ xp: { items: [], gained: 0, bonus: false, capped: false, before: LEVEL(3, 50, 300), after: LEVEL(3, 50, 300) } }),
  );
  await finishWorkoutOne();
  await find('Locked in.');
  await wait(1500);

  expect(screen.queryByText(/XP$/)).toBeNull();
});

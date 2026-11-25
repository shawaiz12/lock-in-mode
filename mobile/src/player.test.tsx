/**
 * The workout player through the REAL screens and navigator, with the API faked and
 * time faked: plan -> preview -> warm-up timer -> sets and rests -> "How did that feel?"
 * -> what changed -> back to the plan. Plus continuing, editing, HIIT running by itself,
 * swaps, a failed save, and the next block.
 */
import { notifyManager, onlineManager } from '@tanstack/react-query';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import type { Plan, Profile, Session, SessionResult, WorkoutDetail } from '@/api/endpoints';
import * as endpoints from '@/api/endpoints';
import { resetStorage } from '@/test/kv-store';
import { setConnected } from '@/test/network';
import { detail, row, timed, workout } from '@/test/fixtures';

jest.mock('@/api/client', () => ({
  auth: { ensureSignedIn: jest.fn(async () => {}), forget: jest.fn(async () => {}) },
  api: {},
}));

jest.mock('@/api/endpoints', () => ({
  ...jest.requireActual('@/api/endpoints'),
  getProfileOrNull: jest.fn(),
  saveProfile: jest.fn(),
  getOrCreatePlan: jest.fn(),
  getWorkout: jest.fn(),
  getOpenSessionOrNull: jest.fn(),
  startSession: jest.fn(),
  getExercise: jest.fn(),
  logSet: jest.fn(),
  deleteSet: jest.fn(),
  finishSession: jest.fn(),
  skipWorkout: jest.fn(),
  swapExercise: jest.fn(),
  sayWhereItHurts: jest.fn(),
  startNextBlock: jest.fn(),
}));

const mockAlerts = { countIn: jest.fn(), done: jest.fn(), ticked: jest.fn() };
jest.mock('@/ui/alerts', () => ({ useAlerts: () => mockAlerts }));
jest.mock('expo-keep-awake', () => ({ useKeepAwake: jest.fn() }));

const api = jest.mocked(endpoints);
/** Any phone time (ISO): the journal sends when each thing happened (ADR 0033). */
const AT = expect.any(String);
notifyManager.setScheduler((callback) => callback());

// A whole-app test does a lot: on a fresh checkout (CI) the first one also compiles every
// screen. Jest's default of 5 s per test is too tight on a busy machine.
jest.setTimeout(30_000);

// What the phone saved (the cache, the journal) starts empty, and the phone online.
beforeEach(() => {
  resetStorage();
  setConnected(true);
  onlineManager.setOnline(true);
});

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

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
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
    ...overrides,
  };
}

/** Warm-up: one 5 s move. Main: dumbbell bench 2 × 8–12 at 40 kg, 60 s rest. */
const BENCH: WorkoutDetail = workout({
  warm_up: [timed('wu', 'March in place', { seconds: 5 })],
  main: [row('a', 'Dumbbell bench press', { sets: 2, rest_seconds: 60, weight_kg: 40 })],
});

function session(sets: Session['sets'] = []): Session {
  return { id: 's1', workout_id: 'w1', started_at: '2026-11-25T10:00:00Z', finished_at: null, feedback: null, sets };
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
    ...overrides,
  };
}

function setUp(w: WorkoutDetail = BENCH, open: Session | null = null) {
  api.getProfileOrNull.mockResolvedValue(PROFILE);
  api.getOrCreatePlan.mockResolvedValue({ plan: plan(), justCreated: false });
  api.getWorkout.mockResolvedValue(w);
  api.getOpenSessionOrNull.mockResolvedValue(open);
  api.startSession.mockResolvedValue(open ?? session());
  api.getExercise.mockImplementation(async (id: string) =>
    detail(id, { equipment: id === 'x-a' ? ['dumbbells'] : [], is_timed: id.startsWith('x-wu') }),
  );
  api.logSet.mockImplementation(async (where, body) => ({
    planned_exercise_id: where.plannedExerciseId,
    set_number: where.setNumber,
    reps: body.reps ?? null,
    weight_kg: body.weight_kg ?? null,
    seconds: body.seconds ?? null,
  }));
  api.finishSession.mockResolvedValue(result());
}

beforeEach(() => {
  jest.clearAllMocks();
});

/** Tap the element showing `target` (or an element already found). */
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
    // The current set's label shows in its card and in the list below: either will do.
    const [element] = screen.queryAllByText(text);
    if (element) return element;
    await wait(50);
  }
  return screen.getByText(text);
}

/** Plan -> preview -> player. */
async function openPlayer() {
  const router = await renderRouter('./src/app');
  await tap(await find('Lock In: workout 1'));
  await tap(await find('Lock In: start'));
  return router;
}

it('does a whole workout: timer, sets, rest, feedback, what changed, back to the plan', async () => {
  setUp();
  api.finishSession.mockResolvedValue(
    result({ progress: [{ exercise: { id: 'x-a', slug: 'a', name: 'Dumbbell bench press', difficulty: 2 }, change: 'heavier', weight_kg: 42.5, seconds: null, set_change: 0 }] }),
  );
  const router = await openPlayer();

  // Warm-up: one Start runs the timer; at zero it beeps, buzzes and logs by itself.
  expect(await find('Lock In: start warm-up')).toBeOnTheScreen();
  expect(router.getPathname()).toBe('/workout/w1/play');
  expect(api.startSession).toHaveBeenCalledWith('w1', AT);
  await tap('Lock In: start warm-up');
  expect(await find('0:05')).toBeOnTheScreen();
  await wait(5_100);
  expect(mockAlerts.done).toHaveBeenCalledTimes(1);
  expect(api.logSet).toHaveBeenCalledWith(
    { sessionId: 's1', plannedExerciseId: 'wu', setNumber: 1 },
    { reps: null, weight_kg: null, seconds: 5, logged_at: AT },
  );

  // Main: pre-filled at the bottom of the range with the suggested weight; one tap.
  expect(await find('Set 1 of 2')).toBeOnTheScreen();
  await tap('✓ 8 reps · 40 kg');
  expect(api.logSet).toHaveBeenLastCalledWith(
    { sessionId: 's1', plannedExerciseId: 'a', setNumber: 1 },
    { reps: 8, weight_kg: 40, seconds: null, logged_at: AT },
  );

  // Rest: counts down, then beeps and shows the next set.
  expect(await find('1:00')).toBeOnTheScreen();
  expect(screen.getByText('Up next: Dumbbell bench press · set 2 of 2')).toBeOnTheScreen();
  await wait(60_100);
  expect(mockAlerts.done).toHaveBeenCalledTimes(2);
  expect(await find('Set 2 of 2')).toBeOnTheScreen();
  await tap(await find('✓ 8 reps · 40 kg'));

  // Last set: no rest, straight to the question.
  expect(await find('Workout done')).toBeOnTheScreen();
  await tap('Just right');
  expect(await find('Locked in.')).toBeOnTheScreen();
  expect(api.finishSession).toHaveBeenCalledWith('s1', 'just_right', AT);
  expect(screen.getByText('Stepping up')).toBeOnTheScreen();
  expect(screen.getByText('Dumbbell bench press: 42.5 kg next time')).toBeOnTheScreen();

  await tap('Lock In: done');
  await wait(200);
  expect(router.getPathname()).toBe('/plan');
});

it('continues an open workout where it was left', async () => {
  const open = session([
    { planned_exercise_id: 'wu', set_number: 1, reps: null, weight_kg: null, seconds: 5 },
    { planned_exercise_id: 'a', set_number: 1, reps: 10, weight_kg: 40, seconds: null },
  ]);
  setUp(BENCH, open);

  await renderRouter('./src/app');
  await tap(await find('Lock In: continue workout 1'));

  expect(await find('Set 2 of 2')).toBeOnTheScreen();
  expect(screen.getByText('2 of 3 sets')).toBeOnTheScreen(); // the warm-up move and set 1 were logged before
});

it('changes a set before ticking it: − / + by a real weight step', async () => {
  setUp(workout({ main: [row('a', 'Dumbbell bench press', { sets: 1, weight_kg: 40 })] }));
  await openPlayer();

  await tap(await find('change'));
  await fireEvent.press(screen.getByLabelText('More reps'));
  await fireEvent.press(screen.getByLabelText('More reps'));
  await fireEvent.press(screen.getByLabelText('More weight'));
  await tap('Save');

  await tap(await find('✓ 10 reps · 42.5 kg'));
  expect(api.logSet).toHaveBeenCalledWith(expect.anything(), { reps: 10, weight_kg: 42.5, seconds: null, logged_at: AT });
});

it('runs HIIT by itself after one Start: work, rest, next move, every round', async () => {
  setUp(
    workout({
      format: 'intervals',
      kind: 'hiit',
      main: [
        timed('h1', 'Squat jump', { sets: 2, seconds: 3, rest_seconds: 2, effort: 8 }),
        timed('h2', 'High knees', { sets: 2, seconds: 3, rest_seconds: 2, effort: 8 }),
      ],
    }),
  );
  await openPlayer();

  await tap(await find('Lock In: start HIIT'));
  await wait(3 * 3_000 + 3 * 2_000 + 3_500);

  expect(api.logSet).toHaveBeenCalledTimes(4);
  expect(mockAlerts.countIn).toHaveBeenCalled(); // 3, 2, 1 before each end
  expect(await find('Workout done')).toBeOnTheScreen();
});

it('the strength test asks how many, then saves it', async () => {
  setUp(workout({ main: [row('a', 'Push-up', { sets: 1, reps_min: null, reps_max: null, is_test: true })] }));
  await openPlayer();

  expect(await find('As many good reps as you can, stop with 2 left')).toBeOnTheScreen();
  await tap('How many did you do?');
  await fireEvent.changeText(screen.getByLabelText('Reps'), '14');
  await tap('Save');
  await tap(await find('✓ Save 14 reps'));

  expect(api.logSet).toHaveBeenCalledWith(expect.anything(), { reps: 14, weight_kg: null, seconds: null, logged_at: AT });
});

it('"This hurts": swaps it, asks where, and offers a limit after the workout', async () => {
  setUp(workout({ main: [row('a', 'Dumbbell bench press', { sets: 1 })] }));
  const swapped = workout({
    main: [
      row('a', 'Dumbbell bench press', { sets: 1, swapped_out: true }),
      row('b', 'Floor press', { sets: 1 }),
    ],
  });
  api.swapExercise.mockResolvedValue({
    workout: swapped,
    swapped_out: { id: 'x-a', slug: 'a', name: 'Dumbbell bench press', difficulty: 2 },
    swapped_in: { id: 'x-b', slug: 'b', name: 'Floor press', difficulty: 2 },
    left_out: false,
  });
  api.sayWhereItHurts.mockResolvedValue('shoulders');
  api.saveProfile.mockImplementation(async (body) => ({ ...PROFILE, ...body }) as Profile);
  await openPlayer();

  await tap(await find('More'));
  await tap('This hurts: swap it');
  expect(await find('Dumbbell bench press → Floor press')).toBeOnTheScreen();
  expect(api.swapExercise).toHaveBeenCalledWith('w1', 'a', 'x-a', 'hurts');
  await tap('Shoulders');
  expect(api.sayWhereItHurts).toHaveBeenCalledWith('x-a', 'shoulders');

  await tap(await find(/^✓ /));
  await tap(await find('Skip'));
  expect(await find('Go easy on your shoulders in every workout?')).toBeOnTheScreen();
  expect(api.finishSession).toHaveBeenCalledWith('s1', null, AT);
  await tap('Yes');
  await wait(100);
  expect(api.saveProfile).toHaveBeenCalledWith(expect.objectContaining({ limits: ['shoulders'] }));
});

it('a set that could not be sent waits on the phone, and goes when asked', async () => {
  setUp(workout({ main: [row('a', 'Push-up', { sets: 2, rest_seconds: 0 })] }));
  api.logSet.mockRejectedValueOnce(new TypeError('Network request failed'));
  await openPlayer();

  await tap(await find('✓ 8 reps'));
  expect(await find('1 set is saved on this phone. It syncs when you’re online.')).toBeOnTheScreen();
  await tap('Try now');
  await wait(100);

  expect(screen.queryByText('1 set is saved on this phone. It syncs when you’re online.')).toBeNull();
  expect(api.logSet).toHaveBeenCalledTimes(2);
});

it('finishing sends a set that failed first, then shows what changed', async () => {
  setUp(workout({ main: [row('a', 'Push-up', { sets: 1 })] }));
  api.logSet.mockRejectedValueOnce(new TypeError('Network request failed'));
  await openPlayer();

  await tap(await find('✓ 8 reps'));
  await tap(await find('Just right'));

  expect(await find('Locked in.')).toBeOnTheScreen();
  expect(api.logSet).toHaveBeenCalledTimes(2);
  const [lastSet] = api.logSet.mock.invocationCallOrder.slice(-1);
  expect(lastSet).toBeLessThan(api.finishSession.mock.invocationCallOrder[0] ?? 0);
});

it('finishing early still counts, and can be taken back', async () => {
  setUp();
  await openPlayer();

  await tap(await find('More'));
  await tap('Finish workout now');
  expect(await find('Ending here?')).toBeOnTheScreen();
  await tap('‹ Keep going');
  expect(await find('Lock In: start warm-up')).toBeOnTheScreen();
});

it('starts the next block once this one is complete, after "Ready for more?"', async () => {
  setUp();
  const done = plan({
    block_complete: true,
    next_workout_id: null,
    level_up: {
      to: 'some_experience',
      reason: 'strength_marks',
      good_weeks: 4,
      what_changes: ['A little more volume each week.'],
      check_with_doctor: false,
    },
  });
  api.getOrCreatePlan.mockResolvedValue({ plan: done, justCreated: false });
  api.startNextBlock.mockResolvedValue(plan({ id: 'plan-2', block_number: 2 }));

  await renderRouter('./src/app');
  expect(await find('Ready for more?')).toBeOnTheScreen();
  expect(screen.getByText('A little more volume each week.')).toBeOnTheScreen();
  await tap('Yes, move up');

  expect(await find('Block 2 · 5 weeks')).toBeOnTheScreen();
  expect(api.startNextBlock).toHaveBeenCalledWith(true);
});

it('without an offer, the button starts the next block', async () => {
  setUp();
  api.getOrCreatePlan.mockResolvedValue({ plan: plan({ block_complete: true, next_workout_id: null }), justCreated: false });
  api.startNextBlock.mockResolvedValue(plan({ id: 'plan-2', block_number: 2 }));

  await renderRouter('./src/app');
  await tap(await find('Lock In: start block 2'));

  expect(await find('Block 2 · 5 weeks')).toBeOnTheScreen();
  expect(api.startNextBlock).toHaveBeenCalledWith(false);
});

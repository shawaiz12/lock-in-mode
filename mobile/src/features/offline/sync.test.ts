import { ApiError, SignedOutError } from '@/api/problem';

import { begin, finishHere, type Journal, record } from './journal';
import { runSync, type SyncApi } from './sync';

const T0 = '2026-11-25T10:00:00.000Z';
const T1 = '2026-11-25T10:05:00.000Z';
const T2 = '2026-11-25T10:40:00.000Z';
const EIGHT = { reps: 8, weight_kg: 40, seconds: null };
const offline = () => new TypeError('Network request failed');

function store(initial: Journal | null) {
  let current = initial;
  return {
    get: () => current,
    update: (workoutId: string, change: (j: Journal) => Journal) => {
      if (current && current.workoutId === workoutId) current = change(current);
    },
    set: (j: Journal) => {
      current = j;
    },
  };
}

function fn<K extends keyof SyncApi>(impl: SyncApi[K]) {
  return jest.fn<ReturnType<SyncApi[K]>, Parameters<SyncApi[K]>>(impl as never);
}

function fakeApi(): jest.Mocked<SyncApi> {
  return {
    start: fn<'start'>(async (workoutId, startedAt) => ({
      id: 's1',
      workout_id: workoutId,
      started_at: startedAt,
      finished_at: null,
      feedback: null,
      sets: [],
    })),
    logSet: fn<'logSet'>(async () => ({})),
    deleteSet: fn<'deleteSet'>(async () => {}),
    finish: fn<'finish'>(async (sessionId) => ({
      id: sessionId,
      workout_id: 'w1',
      started_at: T0,
      finished_at: T2,
      feedback: 'just_right' as const,
      sets: [],
      placements: [],
      progress: [],
      intervals: null,
      recovery_earned: false,
      next_workout_id: 'w2',
      block_complete: false,
      sign_in_offer: null,
    })),
  };
}

/** A workout done offline: started, two sets, finished. */
function doneOffline(): Journal {
  let j = begin('w1', 1, T0);
  j = record(j, 'a', 1, EIGHT, T1);
  j = record(j, 'a', 2, EIGHT, T1);
  return finishHere(j, 'just_right', T2);
}

it('sends a whole offline workout in order, with the phone’s times', async () => {
  const s = store(doneOffline());
  const api = fakeApi();

  expect(await runSync(s, api)).toBe('done');

  expect(api.start).toHaveBeenCalledWith('w1', T0);
  expect(api.logSet).toHaveBeenNthCalledWith(
    1,
    { sessionId: 's1', plannedExerciseId: 'a', setNumber: 1 },
    { reps: 8, weight_kg: 40, seconds: null, logged_at: T1 },
  );
  expect(api.logSet).toHaveBeenCalledTimes(2);
  expect(api.finish).toHaveBeenCalledWith('s1', 'just_right', T2);
  expect(s.get()?.done).toBe(true);
  expect(s.get()?.result?.next_workout_id).toBe('w2');
});

it('stops without a connection and carries on from there next time', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.logSet.mockResolvedValueOnce({}).mockRejectedValueOnce(offline());

  expect(await runSync(s, api)).toBe('offline');
  expect(s.get()?.done).toBe(false);
  expect(api.finish).not.toHaveBeenCalled();

  expect(await runSync(s, api)).toBe('done');
  expect(api.start).toHaveBeenCalledTimes(1); // the start isn't sent again
  expect(api.logSet).toHaveBeenCalledTimes(3); // set 1 once, set 2 twice
});

it('a busy server (429, 5xx) means later, not lost', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.start.mockRejectedValueOnce(new ApiError(503, 'http_error'));
  expect(await runSync(s, api)).toBe('later');
  expect(s.get()?.lost).toBeNull();
});

it('the plan moved on: this workout can’t be saved', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.start.mockRejectedValueOnce(new ApiError(409, 'not_next_workout'));

  expect(await runSync(s, api)).toBe('lost');
  expect(s.get()?.lost).toBe('plan_moved');
  expect(api.logSet).not.toHaveBeenCalled();
});

it('a set the server refuses is dropped; the rest still goes', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.logSet.mockRejectedValueOnce(new ApiError(404, 'not_found'));

  expect(await runSync(s, api)).toBe('done');
  expect(s.get()?.dropped).toBe(1);
  expect(api.logSet).toHaveBeenCalledTimes(2);
});

it('"already finished" on the finish: it got there before, only its answer was lost', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.finish.mockRejectedValueOnce(new ApiError(409, 'session_finished'));

  expect(await runSync(s, api)).toBe('done');
  expect(s.get()).toMatchObject({ done: true, result: null, lost: null });
});

it('an ended sign-in loses the journal', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.start.mockRejectedValueOnce(new SignedOutError());
  expect(await runSync(s, api)).toBe('lost');
  expect(s.get()?.lost).toBe('signed_out');
});

it('a session gone from the server loses the journal', async () => {
  const s = store(doneOffline());
  const api = fakeApi();
  api.logSet.mockRejectedValueOnce(new ApiError(404, 'session_not_found'));
  expect(await runSync(s, api)).toBe('lost');
  expect(s.get()?.lost).toBe('gone');
});

it('a tick made while sending is sent in the same run', async () => {
  const s = store(record(begin('w1', 1, T0), 'a', 1, EIGHT, T1));
  const api = fakeApi();
  api.start.mockImplementationOnce(async (workoutId, startedAt) => {
    const current = s.get();
    if (current) s.set(record(current, 'a', 2, EIGHT, T1)); // ticked during the request
    return { id: 's1', workout_id: workoutId, started_at: startedAt, finished_at: null, feedback: null, sets: [] };
  });

  expect(await runSync(s, api)).toBe('nothing');
  expect(api.logSet).toHaveBeenCalledTimes(2);
});

it('nothing to send: nothing happens', async () => {
  const api = fakeApi();
  expect(await runSync(store(null), api)).toBe('nothing');
  expect(api.start).not.toHaveBeenCalled();
});

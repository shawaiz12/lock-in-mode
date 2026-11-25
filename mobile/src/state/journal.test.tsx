import { onlineManager } from '@tanstack/react-query';

import type { SyncApi } from '@/features/offline/sync';
import { createJournalStore, JOURNAL_KEY, type KeyValue } from '@/state/journal';

const T0 = '2026-11-25T10:00:00.000Z';
const EIGHT = { reps: 8, weight_kg: null, seconds: null };

function memory(): KeyValue & { items: Map<string, string> } {
  const items = new Map<string, string>();
  return {
    items,
    getItemSync: (key) => items.get(key) ?? null,
    setItemSync: (key, value) => {
      items.set(key, value);
    },
    removeItemSync: (key) => items.delete(key),
  };
}

function api(): jest.Mocked<SyncApi> {
  return {
    start: jest.fn(async (workoutId: string, startedAt: string) => ({
      id: 's1',
      workout_id: workoutId,
      started_at: startedAt,
      finished_at: null,
      feedback: null,
      sets: [],
    })),
    logSet: jest.fn(async () => ({})),
    deleteSet: jest.fn(async () => {}),
    finish: jest.fn(),
  } as unknown as jest.Mocked<SyncApi>;
}

beforeEach(() => {
  jest.useFakeTimers();
  onlineManager.setOnline(true);
});

afterEach(() => {
  jest.useRealTimers();
});

it('writes every change to the phone at once, before anything is sent', () => {
  const storage = memory();
  const store = createJournalStore({ storage, api: api() });
  onlineManager.setOnline(false);

  store.begin('w1', 1, T0);
  store.record('a', 1, EIGHT, T0);

  expect(JSON.parse(storage.items.get(JOURNAL_KEY) ?? 'null')).toMatchObject({
    workoutId: 'w1',
    sets: { 'a/1': { entry: EIGHT, version: 1, sent: 0 } },
  });
});

it('a restarted app reads the journal back', () => {
  const storage = memory();
  const first = createJournalStore({ storage, api: api() });
  first.begin('w1', 1, T0);
  first.record('a', 1, EIGHT, T0);

  const again = createJournalStore({ storage, api: api() });
  expect(again.current()?.sets['a/1']?.entry).toEqual(EIGHT);
});

it('clearing removes it from the phone', () => {
  const storage = memory();
  const store = createJournalStore({ storage, api: api() });
  store.begin('w1', 1, T0);
  store.clear();
  expect(storage.items.has(JOURNAL_KEY)).toBe(false);
});

it('known to be offline: doesn’t even try', async () => {
  const fake = api();
  const store = createJournalStore({ storage: memory(), api: fake });
  onlineManager.setOnline(false);
  store.begin('w1', 1, T0);

  expect(await store.sync()).toBe('offline');
  expect(fake.start).not.toHaveBeenCalled();
});

it('without a connection, tries again by itself a little later', async () => {
  const fake = api();
  fake.start.mockRejectedValueOnce(new TypeError('Network request failed'));
  const store = createJournalStore({ storage: memory(), api: fake });
  store.begin('w1', 1, T0);

  expect(await store.sync()).toBe('offline');
  await jest.advanceTimersByTimeAsync(5_000);

  expect(fake.start).toHaveBeenCalledTimes(2);
  expect(store.current()?.sessionId).toBe('s1');
});

it('a tick made while a send is running goes in the same run or right after it', async () => {
  const fake = api();
  const store = createJournalStore({ storage: memory(), api: fake });
  store.begin('w1', 1, T0);
  const first = store.sync();
  store.record('a', 1, EIGHT, T0); // during the start request
  await first;
  await jest.advanceTimersByTimeAsync(0);

  expect(fake.logSet).toHaveBeenCalledTimes(1);
  expect(store.current()?.sets['a/1']).toMatchObject({ version: 1, sent: 1 });
});

it('tells the app when the server has the start', async () => {
  const onChange = jest.fn();
  const store = createJournalStore({ storage: memory(), api: api(), onChange });
  store.begin('w1', 1, T0);
  await store.sync();
  const [before, after] = onChange.mock.calls.at(-1) ?? [];
  expect(before?.sessionId).toBeNull();
  expect(after?.sessionId).toBe('s1');
});

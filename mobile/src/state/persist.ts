/**
 * What the phone keeps between launches, so the app opens and the next workout runs with
 * no connection (ADR 0033): the profile, the plan, workouts and exercise pages. Saved by
 * TanStack Query's persister into expo-sqlite's key-value store, a second or so after
 * anything changes, and read back when the app starts.
 *
 * Kept for 14 days (`OFFLINE_DAYS`). A workout downloaded longer ago than that can't be
 * started offline: after two weeks away the plan eases you back in (ADR 0021), and an old
 * copy wouldn't know. Connecting once gets a fresh one.
 *
 * Not kept: the sign-in check (the tokens are in the secure store already) and anything
 * that failed. The workout in progress is NOT here: it's in the journal
 * (src/state/journal.tsx), which saves every tick at once.
 * .NET: like an offline cache of HttpClient responses on disk, with an expiry.
 */
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import type { Query } from '@tanstack/react-query';
import type { PersistQueryClientOptions } from '@tanstack/react-query-persist-client';
import Storage from 'expo-sqlite/kv-store';

export const OFFLINE_DAYS = 14;
export const OFFLINE_MS = OFFLINE_DAYS * 24 * 60 * 60 * 1000;

/** Where it's saved, in expo-sqlite's key-value store. */
export const CACHE_KEY = 'lockin.cache';

/** Change it when what's saved changes shape: older saved data is then thrown away. */
export const CACHE_VERSION = '1';

/** The first part of the query keys worth keeping (src/state/startup.ts `keys`). */
const KEPT = new Set(['profile', 'plan', 'workout', 'exercise', 'workout-session']);

export function shouldKeep(query: Pick<Query, 'queryKey' | 'state'>): boolean {
  return query.state.status === 'success' && KEPT.has(String(query.queryKey[0]));
}

/** Can this workout start with no connection? Its copy must be here, and recent. */
export function offlineReady(
  copy: { dataUpdatedAt: number; data?: unknown } | undefined,
  now: number,
): 'ready' | 'missing' | 'stale' {
  if (!copy || copy.data === undefined) return 'missing';
  return now - copy.dataUpdatedAt > OFFLINE_MS ? 'stale' : 'ready';
}

export const persistOptions: Omit<PersistQueryClientOptions, 'queryClient'> = {
  persister: createAsyncStoragePersister({ storage: Storage, key: CACHE_KEY, throttleTime: 1000 }),
  maxAge: OFFLINE_MS,
  buster: CACHE_VERSION,
  dehydrateOptions: { shouldDehydrateQuery: shouldKeep },
};

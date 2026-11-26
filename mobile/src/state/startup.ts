/**
 * Where should the person be right now? One answer drives the whole navigator
 * (src/app/_layout.tsx): it unlocks exactly one group of screens, and Expo Router moves
 * the person there by itself when the answer changes.
 *
 *   no sign-in yet / loading -> "loading"     (spinner)
 *   something failed         -> "error"       (message + Try again)
 *   offline, nothing saved   -> "offline"     (connect once to set up)
 *   no profile (404)         -> "onboarding"
 *   profile, no safety check -> "safety"
 *   all done                 -> "plan"
 *
 * Offline (ADR 0033): the profile saved on the phone is enough to carry on, even when
 * refreshing it fails. Only an ended sign-in always stops here.
 *
 * Whose copy is it? Everything saved on the phone (the cache, the journal) belongs to
 * the account that saved it. A brand-new guest is a new, empty account, so the old copy
 * is thrown away (`startFresh`): otherwise a phone whose account was erased would show
 * the old plan to an account that hasn't even done onboarding. An ended sign-in found by
 * any call, on any screen, brings the app back here ("Start again").
 *
 * .NET: like a state machine that picks the start page after login.
 */
import { QueryClient, useQuery, useQueryClient } from '@tanstack/react-query';
import Storage from 'expo-sqlite/kv-store';
import { useEffect } from 'react';

import { auth } from '@/api/client';
import { getProfileOrNull, type Profile } from '@/api/endpoints';
import { ApiError, SignedOutError } from '@/api/problem';
import { useJournalStore } from '@/state/journal';
import { useOnline } from '@/state/online';
import { CACHE_KEY, OFFLINE_MS } from '@/state/persist';

export const keys = {
  session: ['session'] as const,
  /** True once a call finds the sign-in has ended. Only in memory, never saved. */
  signedOut: ['signed-out'] as const,
  profile: ['profile'] as const,
  plan: ['plan'] as const,
  workout: (id: string) => ['workout', id] as const,
  /** The account and its settings (GET /me). */
  me: ['me'] as const,
  /** The Lock In level and XP (GET /me/xp). */
  xp: ['me', 'xp'] as const,
  /** This week's ring and the streak (GET /me/week). */
  week: ['me', 'week'] as const,
  /** The workout in progress on the server, if any (GET /sessions/current). */
  openSession: ['workout-session', 'open'] as const,
  exercise: (id: string) => ['exercise', id] as const,
};

export type Stage = 'loading' | 'error' | 'offline' | 'onboarding' | 'safety' | 'plan';

type QueryState<T> = { status: 'pending' | 'error' | 'success'; data?: T; error?: unknown };

/** Pure, so it's tested without React. */
export function stageFor(
  session: QueryState<unknown>,
  profile: QueryState<Profile | null>,
  online = true,
  signedOut = false,
): Stage {
  if (signedOut) return 'error';
  if (session.status === 'error' || profile.error instanceof SignedOutError) return 'error';
  if (session.status === 'pending') return 'loading';
  // What's on the phone counts, even if refreshing it just failed.
  if (profile.data !== undefined) {
    if (profile.data === null) return 'onboarding';
    if (profile.data.safety_screened_at === null) return 'safety';
    return 'plan';
  }
  if (profile.status === 'error') return 'error';
  return online ? 'loading' : 'offline';
}

/** Retry network blips and 5xx; never retry what retrying can't fix. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof SignedOutError) return false;
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < 2;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // gcTime: keep what's saved on the phone as long as it may be used offline
      // (src/state/persist.ts); a query dropped from memory is dropped from the phone too.
      queries: { retry: shouldRetry, staleTime: 30_000, gcTime: OFFLINE_MS },
      mutations: { retry: false },
    },
  });
}

/** A new account: nothing the phone saved for the previous one belongs to it. Drops every
 * cached answer but the sign-in check, the saved copy of them, and any journal.
 * .NET: like clearing a per-user cache folder when a different user logs in. */
export function startFresh(queryClient: QueryClient, journal: { clear(): void }): void {
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== keys.session[0] });
  // At once, not a second later like the persister: an app closed right now must not
  // read the old copy back at the next launch.
  Storage.removeItemSync(CACHE_KEY);
  journal.clear();
}

const SIGNED_OUT = new SignedOutError();

export function useStartup() {
  const queryClient = useQueryClient();
  const journal = useJournalStore();
  const online = useOnline();
  const signedOut =
    useQuery({
      queryKey: keys.signedOut,
      queryFn: () => false,
      staleTime: Infinity,
      networkMode: 'always',
    }).data === true;
  // Any call that finds the sign-in ended (a screen, the journal) brings everyone here.
  useEffect(
    () => auth.onSignedOut(() => queryClient.setQueryData(keys.signedOut, true)),
    [queryClient],
  );
  const session = useQuery({
    queryKey: keys.session,
    queryFn: async () => {
      if (await auth.ensureSignedIn()) startFresh(queryClient, journal);
      return true;
    },
    staleTime: Infinity,
    // Signed in already = no network needed: don't wait for one.
    networkMode: 'always',
  });
  const profile = useQuery({
    queryKey: keys.profile,
    queryFn: getProfileOrNull,
    enabled: session.isSuccess,
    staleTime: Infinity, // changed only by our own saves, which update it directly
  });
  const stage = stageFor(session, profile, online, signedOut);
  const error = signedOut ? SIGNED_OUT : (session.error ?? profile.error);

  async function retry() {
    if (error instanceof SignedOutError) {
      // The old sign-in can't come back: start again as a new guest, with nothing of the
      // old account's left. Signing in again happens from scratch (ensureSignedIn).
      await auth.forget();
      startFresh(queryClient, journal);
      // Not awaited: the screen follows the sign-in check by itself (spinner, then
      // onboarding or "Can't reach"), and retries can take a few seconds.
      void queryClient.resetQueries({ queryKey: keys.session });
      return;
    }
    await (session.isError ? session.refetch() : profile.refetch());
  }

  return { stage, error, retry };
}

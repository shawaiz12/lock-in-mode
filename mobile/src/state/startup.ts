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
 * .NET: like a state machine that picks the start page after login.
 */
import { QueryClient, useQuery, useQueryClient } from '@tanstack/react-query';

import { auth } from '@/api/client';
import { getProfileOrNull, type Profile } from '@/api/endpoints';
import { ApiError, SignedOutError } from '@/api/problem';
import { useOnline } from '@/state/online';
import { OFFLINE_MS } from '@/state/persist';

export const keys = {
  session: ['session'] as const,
  profile: ['profile'] as const,
  plan: ['plan'] as const,
  workout: (id: string) => ['workout', id] as const,
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
): Stage {
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

export function useStartup() {
  const queryClient = useQueryClient();
  const online = useOnline();
  const session = useQuery({
    queryKey: keys.session,
    queryFn: async () => {
      await auth.ensureSignedIn();
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
  const stage = stageFor(session, profile, online);
  const error = session.error ?? profile.error;

  async function retry() {
    if (error instanceof SignedOutError) {
      // The old sign-in can't come back: start again as a new guest.
      await auth.forget();
      queryClient.clear();
    }
    await (session.isError ? session.refetch() : profile.refetch());
  }

  return { stage, error, retry };
}

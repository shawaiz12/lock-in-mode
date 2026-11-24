/**
 * Where should the person be right now? One answer drives the whole navigator
 * (src/app/_layout.tsx): it unlocks exactly one group of screens, and Expo Router moves
 * the person there by itself when the answer changes.
 *
 *   no sign-in yet / loading -> "loading"     (spinner)
 *   something failed         -> "error"       (message + Try again)
 *   no profile (404)         -> "onboarding"
 *   profile, no safety check -> "safety"
 *   all done                 -> "plan"
 *
 * .NET: like a state machine that picks the start page after login.
 */
import { QueryClient, useQuery, useQueryClient } from '@tanstack/react-query';

import { auth } from '@/api/client';
import { getProfileOrNull, type Profile } from '@/api/endpoints';
import { ApiError, SignedOutError } from '@/api/problem';

export const keys = {
  session: ['session'] as const,
  profile: ['profile'] as const,
  plan: ['plan'] as const,
  workout: (id: string) => ['workout', id] as const,
};

export type Stage = 'loading' | 'error' | 'onboarding' | 'safety' | 'plan';

type QueryState<T> = { status: 'pending' | 'error' | 'success'; data?: T };

/** Pure, so it's tested without React. */
export function stageFor(session: QueryState<unknown>, profile: QueryState<Profile | null>): Stage {
  if (session.status === 'error' || profile.status === 'error') return 'error';
  if (session.status === 'pending' || profile.status === 'pending') return 'loading';
  if (profile.data === null || profile.data === undefined) return 'onboarding';
  if (profile.data.safety_screened_at === null) return 'safety';
  return 'plan';
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
      queries: { retry: shouldRetry, staleTime: 30_000 },
      mutations: { retry: false },
    },
  });
}

export function useStartup() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: keys.session,
    queryFn: async () => {
      await auth.ensureSignedIn();
      return true;
    },
    staleTime: Infinity,
  });
  const profile = useQuery({
    queryKey: keys.profile,
    queryFn: getProfileOrNull,
    enabled: session.isSuccess,
    staleTime: Infinity, // changed only by our own saves, which update it directly
  });
  const stage = stageFor(session, profile);
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

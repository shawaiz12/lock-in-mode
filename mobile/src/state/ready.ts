/**
 * Keeping the next workout ready on the phone (ADR 0033). The plan screen asks for the
 * next workout and its exercise pages as soon as it knows which one is next, while
 * online; TanStack Query keeps them, and src/state/persist.ts saves them to the phone.
 * Offline, the same calls answer from what's saved.
 * .NET: like warming a cache in the background so the next page opens instantly.
 */
import { useQueries, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { getExercise, getWorkout } from '@/api/endpoints';
import { exerciseIds } from '@/state/player';
import { offlineReady } from '@/state/persist';
import { keys } from '@/state/startup';

/** Downloads this workout (and its exercises) and says whether it could start offline. */
export function useReadyOffline(workoutId: string | null | undefined, now: () => number = Date.now) {
  const [openedAt] = useState(now);
  const workout = useQuery({
    queryKey: keys.workout(workoutId ?? ''),
    queryFn: () => getWorkout(workoutId ?? ''),
    enabled: Boolean(workoutId),
  });
  useQueries({
    queries: exerciseIds(workout.data).map((id) => ({
      queryKey: keys.exercise(id),
      queryFn: () => getExercise(id),
      staleTime: Infinity,
    })),
  });
  if (!workoutId) return 'missing' as const;
  return offlineReady(
    workout.data === undefined ? undefined : { data: workout.data, dataUpdatedAt: workout.dataUpdatedAt },
    openedAt,
  );
}

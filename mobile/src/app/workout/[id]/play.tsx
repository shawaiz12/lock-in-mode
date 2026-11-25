/**
 * "/workout/<id>/play": doing the workout (ADR 0032). Opening it starts the workout, or
 * continues it (POST /sessions gives the same session again). Leaving keeps it open: the
 * plan screen then says "continue". The screen stays on while it's open.
 *
 *   playing  ->  "How did that feel?"  ->  what changed  ->  back to the plan
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useKeepAwake } from 'expo-keep-awake';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { type BodyLimit, getProfileOrNull, profileWithChanges, saveProfile } from '@/api/endpoints';
import { describeError, isApiError } from '@/api/problem';
import { usePlayer } from '@/state/player';
import { keys } from '@/state/startup';
import { useAlerts } from '@/ui/alerts';
import { ErrorView, Loading } from '@/ui/kit';
import { FeedbackView, PlayerView, ResultView } from '@/ui/player';

export default function PlayScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  useKeepAwake();
  const alerts = useAlerts();
  const player = usePlayer(id, alerts);
  const [finishing, setFinishing] = useState(false);
  const limit = useLimitOffer(player.suggestLimit);

  if (player.loading) return <Loading message="Getting your workout ready…" />;
  if (player.error) {
    if (isApiError(player.error, 'not_next_workout')) {
      return (
        <ErrorView
          message="This workout isn’t the next one any more: your plan has moved on."
          retryTitle="Back to my plan"
          onRetry={() => router.dismissTo('/plan')}
        />
      );
    }
    return <ErrorView message={describeError(player.error)} onRetry={player.retryLoading} />;
  }
  if (player.result) {
    return (
      <ResultView
        result={player.result}
        position={player.workout?.position ?? null}
        limit={limit.offer}
        onLimit={limit.answer}
        limitSaving={limit.saving}
        onDone={() => router.dismissTo('/plan')}
      />
    );
  }
  if (finishing || player.position === null) {
    return <FeedbackView player={player} onBack={player.position === null ? null : () => setFinishing(false)} />;
  }
  return <PlayerView player={player} onLeave={() => router.back()} onFinishNow={() => setFinishing(true)} />;
}

/** "Go easy on your knees in every workout?" after a "this hurts" swap (ADR 0020
 * decision 3). Only after the workout: saving the profile rebuilds the plan, which
 * would end a workout still in progress. */
function useLimitOffer(suggested: BodyLimit | null) {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: keys.profile, queryFn: getProfileOrNull, staleTime: Infinity });
  const [answered, setAnswered] = useState(false);
  const save = useMutation({
    mutationFn: async (limit: BodyLimit) => {
      if (!profile.data) throw new Error('No profile');
      return saveProfile(profileWithChanges(profile.data, { limits: [...profile.data.limits, limit] }));
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.profile, saved);
      void queryClient.invalidateQueries({ queryKey: keys.plan });
      setAnswered(true);
    },
  });
  const already = suggested !== null && (profile.data?.limits.includes(suggested) ?? true);
  const offer = !answered && !already ? suggested : null;
  return {
    offer,
    saving: save.isPending,
    answer: (yes: boolean) => {
      if (yes && suggested) save.mutate(suggested);
      else setAnswered(true);
    },
  };
}

/**
 * "/workout/<id>/play": doing the workout (ADR 0032). Opening it starts the workout, or
 * continues it. Leaving keeps it open: the plan screen then says "continue". The screen
 * stays on while it's open. Works offline once the workout is on the phone (ADR 0033).
 *
 *   playing  ->  "How did that feel?"  ->  what changed  ->  back to the plan
 *                                      ->  (offline) saved on this phone
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useKeepAwake } from 'expo-keep-awake';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { type BodyLimit, getProfileOrNull, profileWithChanges, saveProfile } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { JournalLostError, NeedsConnectionError, usePlayer } from '@/state/player';
import { keys } from '@/state/startup';
import { useAlerts } from '@/ui/alerts';
import { ErrorView, Loading } from '@/ui/kit';
import { FeedbackView, PlayerView, ResultView, SavedView } from '@/ui/player';

/** Words for what stops a workout from opening. */
function openMessage(error: unknown): string | null {
  if (error instanceof JournalLostError) {
    return error.why === 'signed_out'
      ? 'Your sign-in has ended, so this workout can’t be saved.'
      : 'This workout isn’t the next one any more: your plan has moved on.';
  }
  if (!(error instanceof NeedsConnectionError)) return null;
  switch (error.why) {
    case 'missing':
      return 'This workout isn’t on your phone yet. Connect once to get it ready.';
    case 'stale':
      return 'It’s been a while. Connect once so your next workout fits where you are now.';
    case 'waiting':
      return 'Your last workout is still on this phone. Connect once to sync it, then this one is ready.';
    default:
      return 'This needs a connection.';
  }
}

export default function PlayScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  useKeepAwake();
  const alerts = useAlerts();
  const player = usePlayer(id, alerts);
  const [finishing, setFinishing] = useState(false);
  const limit = useLimitOffer(player.suggestLimit);

  if (player.loading) return <Loading message="Getting your workout ready…" />;
  if (player.error) {
    const message = openMessage(player.error);
    if (message) {
      return (
        <ErrorView
          message={message}
          retryTitle="Back to my plan"
          onRetry={() => {
            player.dropLost();
            router.dismissTo('/plan');
          }}
        />
      );
    }
    return <ErrorView message={describeError(player.error)} onRetry={player.retryLoading} />;
  }
  const close = () => {
    player.close();
    router.dismissTo('/plan');
  };
  if (player.result) {
    return (
      <ResultView
        result={player.result}
        position={player.workout?.position ?? null}
        limit={limit.offer}
        onLimit={limit.answer}
        limitSaving={limit.saving}
        onDone={close}
      />
    );
  }
  if (player.finished && !player.finishing) {
    // Not sent yet (offline): the plan screen shows the results once it is. Sent, but
    // its answer lost on the way: nothing more to show.
    return (
      <SavedView
        position={player.workout?.position ?? null}
        sent={player.done}
        online={player.online}
        onDone={player.done ? close : () => router.dismissTo('/plan')}
      />
    );
  }
  if (finishing || player.finished || player.position === null) {
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

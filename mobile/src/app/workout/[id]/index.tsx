/**
 * "/workout/<id>": one workout before it starts, with what's in it. For the next workout
 * in the queue: "Lock In: start" (or "continue", if it's already open) and "Skip".
 * `[id]` in the folder name is a route parameter, like {id} in an ASP.NET route.
 * Offline (ADR 0033): shows the copy saved on the phone; starts only a recent one.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import {
  getOpenSessionOrNull,
  getOrCreatePlan,
  getWorkout,
  type PlannedExercise,
  skipWorkout,
} from '@/api/endpoints';
import { describeError, isApiError } from '@/api/problem';
import { formatDetails, formatTarget } from '@/features/plan/format';
import { useJournal } from '@/state/journal';
import { useOnline } from '@/state/online';
import { offlineReady } from '@/state/persist';
import { keys } from '@/state/startup';
import {
  Body,
  ErrorView,
  Label,
  Loading,
  LockInButton,
  Screen,
  space,
  TextButton,
  Title,
} from '@/ui/kit';
import { chunky, font, makeStyles } from '@/ui/theme';

export default function WorkoutPreview() {
  const styles = useStyles();
  const { id } = useLocalSearchParams<{ id: string }>();
  const workout = useQuery({ queryKey: keys.workout(id), queryFn: () => getWorkout(id) });
  const plan = useQuery({ queryKey: keys.plan, queryFn: getOrCreatePlan });
  const open = useQuery({ queryKey: keys.openSession, queryFn: getOpenSessionOrNull });
  const online = useOnline();
  const { journal } = useJournal();
  const [openedAt] = useState(Date.now);

  if (workout.isPending) {
    if (!online) {
      return (
        <ErrorView
          message="This workout isn’t on your phone. Connect to see it."
          onRetry={() => workout.refetch()}
        />
      );
    }
    return <Loading />;
  }
  if (workout.data === undefined) {
    return <ErrorView message={describeError(workout.error)} onRetry={() => workout.refetch()} />;
  }
  const w = workout.data;
  const isNext = plan.data?.plan.next_workout_id === w.id && w.status === 'pending';
  const here = journal?.workoutId === w.id && !journal.lost ? journal : null;
  // Another workout finished on this phone and not sent yet: this one waits for it.
  const waitingForOther = journal !== null && !here && journal.finish !== null && !journal.done && !journal.lost;
  const started = open.data?.workout_id === w.id || (here !== null && here.finish === null);
  const canStartOffline = online || offlineReady({ data: w, dataUpdatedAt: workout.dataUpdatedAt }, openedAt) === 'ready';

  let footer;
  if (here?.finish) {
    footer = <LockInButton title="Saved on this phone" disabled onPress={() => {}} />;
  } else if (isNext && waitingForOther) {
    footer = <LockInButton title="Connect to sync your last workout" disabled onPress={() => {}} />;
  } else if (isNext && !canStartOffline) {
    footer = <LockInButton title="Connect once to get it ready" disabled onPress={() => {}} />;
  } else if (isNext) {
    footer = (
      <LockInButton
        title={started ? 'Lock In: continue' : 'Lock In: start'}
        onPress={() => router.push(`/workout/${w.id}/play`)}
      />
    );
  }
  const sections: [string, PlannedExercise[]][] = [
    ['Warm-up', w.warm_up],
    ['Main', w.main],
    ['Finisher', w.finisher],
    ['Cool-down', w.cool_down],
  ];

  return (
    <Screen footer={footer}>
      <Stack.Screen options={{ title: `Workout ${w.position}` }} />
      <Label>
        Week {w.week} · {w.total_minutes} min{w.recovery ? ' · lighter week' : ''}
      </Label>
      <Title>{w.title}</Title>
      {sections
        .filter(([, exercises]) => exercises.length > 0)
        .map(([name, exercises]) => (
          <View key={name} style={styles.section}>
            <Label>{name}</Label>
            {exercises.map((exercise) => (
              <ExerciseRow key={exercise.id} exercise={exercise} />
            ))}
          </View>
        ))}
      {isNext && !started && !here && open.isSuccess && online ? <SkipWorkout workoutId={w.id} /> : null}
    </Screen>
  );
}

/** "Skip this workout" asks once more before it moves the plan on (ADR 0017: skipped
 * workouts never pile up, and a started one can't be skipped: finish it instead). */
function SkipWorkout({ workoutId }: { workoutId: string }) {
  const styles = useStyles();
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const skip = useMutation({
    mutationFn: () => skipWorkout(workoutId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.plan });
      router.back();
    },
  });
  if (!asking) return <TextButton title="Skip this workout" onPress={() => setAsking(true)} />;
  const message = skip.error
    ? isApiError(skip.error, 'session_in_progress')
      ? 'This workout is already started: finish it instead, half counts.'
      : describeError(skip.error)
    : 'Skip it? Your plan moves on to the next workout. Nothing is lost.';
  return (
    <View style={styles.section}>
      <Body muted>{message}</Body>
      <TextButton title={skip.isPending ? 'Skipping…' : 'Yes, skip it'} onPress={() => skip.mutate()} />
      <TextButton title="Keep it" onPress={() => setAsking(false)} />
    </View>
  );
}

function ExerciseRow({ exercise }: { exercise: PlannedExercise }) {
  const styles = useStyles();
  const details = formatDetails(exercise);
  return (
    <View style={[styles.row, exercise.swapped_out && styles.swapped]}>
      <Text style={styles.name}>{exercise.exercise.name}</Text>
      <Text style={styles.target}>{formatTarget(exercise)}</Text>
      {details ? <Text style={styles.details}>{details}</Text> : null}
    </View>
  );
}

const useStyles = makeStyles((p) => ({
  section: { gap: space.s },
  row: {
    ...chunky,
    backgroundColor: p.card,
    borderColor: p.edge,
    borderRadius: 18,
    padding: 14,
    gap: 2,
  },
  swapped: { opacity: 0.4 },
  name: { fontFamily: font.bold, color: p.text, fontSize: 16 },
  target: { fontFamily: font.regular, color: p.text, fontSize: 15 },
  details: { fontFamily: font.regular, color: p.muted, fontSize: 13 },
}));

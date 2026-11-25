/**
 * "/workout/<id>": one workout before it starts, with what's in it. For the next workout
 * in the queue: "Lock In: start" (or "continue", if it's already open) and "Skip".
 * `[id]` in the folder name is a route parameter, like {id} in an ASP.NET route.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import {
  getOpenSessionOrNull,
  getOrCreatePlan,
  getWorkout,
  type PlannedExercise,
  skipWorkout,
} from '@/api/endpoints';
import { describeError, isApiError } from '@/api/problem';
import { formatDetails, formatTarget } from '@/features/plan/format';
import { keys } from '@/state/startup';
import {
  Body,
  colors,
  ErrorView,
  Label,
  Loading,
  LockInButton,
  Screen,
  space,
  TextButton,
  Title,
} from '@/ui/kit';

export default function WorkoutPreview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const workout = useQuery({ queryKey: keys.workout(id), queryFn: () => getWorkout(id) });
  const plan = useQuery({ queryKey: keys.plan, queryFn: getOrCreatePlan });
  const open = useQuery({ queryKey: keys.openSession, queryFn: getOpenSessionOrNull });

  if (workout.isPending) return <Loading />;
  if (workout.isError) {
    return <ErrorView message={describeError(workout.error)} onRetry={() => workout.refetch()} />;
  }
  const w = workout.data;
  const isNext = plan.data?.plan.next_workout_id === w.id && w.status === 'pending';
  const started = open.data?.workout_id === w.id;
  const sections: [string, PlannedExercise[]][] = [
    ['Warm-up', w.warm_up],
    ['Main', w.main],
    ['Finisher', w.finisher],
    ['Cool-down', w.cool_down],
  ];

  return (
    <Screen
      footer={
        isNext ? (
          <LockInButton
            title={started ? 'Lock In: continue' : 'Lock In: start'}
            onPress={() => router.push(`/workout/${w.id}/play`)}
          />
        ) : undefined
      }
    >
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
      {isNext && !started && open.isSuccess ? <SkipWorkout workoutId={w.id} /> : null}
    </Screen>
  );
}

/** "Skip this workout" asks once more before it moves the plan on (ADR 0017: skipped
 * workouts never pile up, and a started one can't be skipped: finish it instead). */
function SkipWorkout({ workoutId }: { workoutId: string }) {
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
  const details = formatDetails(exercise);
  return (
    <View style={[styles.row, exercise.swapped_out && styles.swapped]}>
      <Text style={styles.name}>{exercise.exercise.name}</Text>
      <Text style={styles.target}>{formatTarget(exercise)}</Text>
      {details ? <Text style={styles.details}>{details}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { gap: space.s },
  row: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: space.m,
    gap: 2,
  },
  swapped: { opacity: 0.4 },
  name: { color: colors.text, fontSize: 16, fontWeight: '700' },
  target: { color: colors.text, fontSize: 15 },
  details: { color: colors.muted, fontSize: 13 },
});

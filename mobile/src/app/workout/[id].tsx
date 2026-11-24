/**
 * "/workout/<id>": a read-only look at one workout. The workout player (timers,
 * ticking sets, the finish screen) replaces this in the next stage.
 * `[id]` in the file name is a route parameter, like {id} in an ASP.NET route.
 */
import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';

import { getWorkout, type PlannedExercise } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { formatDetails, formatTarget } from '@/features/plan/format';
import { keys } from '@/state/startup';
import { Body, Card, colors, ErrorView, Label, Loading, Screen, space, Title } from '@/ui/kit';

export default function WorkoutPreview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const workout = useQuery({ queryKey: keys.workout(id), queryFn: () => getWorkout(id) });

  if (workout.isPending) return <Loading />;
  if (workout.isError) {
    return <ErrorView message={describeError(workout.error)} onRetry={() => workout.refetch()} />;
  }
  const w = workout.data;
  const sections: [string, PlannedExercise[]][] = [
    ['Warm-up', w.warm_up],
    ['Main', w.main],
    ['Finisher', w.finisher],
    ['Cool-down', w.cool_down],
  ];

  return (
    <Screen>
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
      <Card>
        <Body muted>The workout player, with timers and one tap per set, is coming in the next update.</Body>
      </Card>
    </Screen>
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

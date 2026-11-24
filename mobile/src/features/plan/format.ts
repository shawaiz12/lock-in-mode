/** Words for plan data: routine names, workout targets, statuses. Pure functions. */
import type { PlannedExercise, WorkoutSummary } from '@/api/endpoints';
import type { components } from '@/api/schema';

type RoutineKind = components['schemas']['RoutineKind'];
type WorkoutStatus = components['schemas']['WorkoutStatus'];

const ROUTINES: Record<RoutineKind, string> = {
  full_body: 'Full body',
  upper_lower: 'Upper / lower',
  push_pull_legs: 'Push pull legs',
  upper_lower_ppl: 'Upper / lower + push pull legs',
  bro_split: 'Bro split',
  strength_and_cardio: 'Strength + cardio',
  circuits_and_cardio: 'Circuits + cardio',
};

export function routineLabel(kind: RoutineKind): string {
  return ROUTINES[kind];
}

const STATUSES: Record<WorkoutStatus, string> = {
  pending: '',
  done: 'Done',
  skipped: 'Skipped',
  replaced_by_recovery: 'Recovery instead',
  replaced_by_break: 'Missed',
};

export function statusLabel(status: WorkoutStatus): string {
  return STATUSES[status];
}

/** 45 -> "45 s", 60 -> "1 min", 90 -> "1 min 30 s". */
export function formatSeconds(total: number): string {
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return seconds === 0 ? `${minutes} min` : `${minutes} min ${seconds} s`;
}

/** What to do, in one line: "3 × 8–12 · 20 kg", "4 × 30 s", "Test: as many good reps as you can". */
export function formatTarget(exercise: PlannedExercise): string {
  const { sets, reps_min, reps_max, seconds, weight_kg, is_test } = exercise;
  let what: string;
  if (is_test && reps_min === null && seconds === null) {
    what = 'Test: as many good reps as you can, stop with 2 left';
  } else if (seconds !== null) {
    what = `${sets} × ${formatSeconds(seconds)}`;
  } else if (reps_min !== null && reps_max !== null && reps_min !== reps_max) {
    what = `${sets} × ${reps_min}–${reps_max}`;
  } else if (reps_min !== null) {
    what = `${sets} × ${reps_min}`;
  } else {
    what = `${sets} ${sets === 1 ? 'set' : 'sets'}`;
  }
  if (weight_kg !== null) what += ` · ${weight_kg} kg`;
  return what;
}

/** The smaller details under the target: rest, warm-up sets, effort. */
export function formatDetails(exercise: PlannedExercise): string {
  const parts: string[] = [];
  if (exercise.rest_seconds > 0) parts.push(`rest ${formatSeconds(exercise.rest_seconds)}`);
  if (exercise.practice_sets > 0) {
    parts.push(`${exercise.practice_sets} light warm-up ${exercise.practice_sets === 1 ? 'set' : 'sets'} first`);
  }
  if (exercise.effort !== null) parts.push(`effort ${exercise.effort}/10`);
  if (exercise.reps_in_reserve !== null) {
    parts.push(`stop with ${exercise.reps_in_reserve} in the tank`);
  }
  return parts.join(' · ');
}

export type WeekGroup = { week: number; workouts: WorkoutSummary[] };

/** The queue, split into weeks, in queue order. */
export function groupByWeek(workouts: readonly WorkoutSummary[]): WeekGroup[] {
  const groups: WeekGroup[] = [];
  for (const workout of [...workouts].sort((a, b) => a.position - b.position)) {
    const last = groups[groups.length - 1];
    if (last && last.week === workout.week) last.workouts.push(workout);
    else groups.push({ week: workout.week, workouts: [workout] });
  }
  return groups;
}

import type { PlannedExercise, WorkoutSummary } from '@/api/endpoints';

import {
  formatDetails,
  formatSeconds,
  formatTarget,
  groupByWeek,
  routineLabel,
  statusLabel,
} from './format';

const exercise = (overrides: Partial<PlannedExercise>): PlannedExercise => ({
  id: 'e1',
  exercise: { id: 'x', slug: 'push-up', name: 'Push-up', difficulty: 3 },
  sets: 3,
  reps_min: 8,
  reps_max: 12,
  seconds: null,
  rest_seconds: 90,
  reps_in_reserve: null,
  effort: null,
  group: 1,
  practice_sets: 0,
  is_test: false,
  swapped_out: false,
  weight_kg: null,
  last: null,
  ...overrides,
});

const workout = (position: number, week: number): WorkoutSummary =>
  ({ id: `w${position}`, position, week }) as WorkoutSummary;

describe('formatSeconds', () => {
  it.each([
    [45, '45 s'],
    [60, '1 min'],
    [90, '1 min 30 s'],
    [1200, '20 min'],
  ])('%i -> %s', (seconds, text) => {
    expect(formatSeconds(seconds)).toBe(text);
  });
});

describe('formatTarget', () => {
  it('shows a rep range, a fixed count, a hold and a weight', () => {
    expect(formatTarget(exercise({}))).toBe('3 × 8–12');
    expect(formatTarget(exercise({ reps_min: 10, reps_max: 10 }))).toBe('3 × 10');
    expect(formatTarget(exercise({ reps_min: null, reps_max: null, seconds: 30 }))).toBe('3 × 30 s');
    expect(formatTarget(exercise({ weight_kg: 22.5 }))).toBe('3 × 8–12 · 22.5 kg');
  });

  it('explains an open strength-test set', () => {
    expect(formatTarget(exercise({ is_test: true, reps_min: null, reps_max: null }))).toMatch(
      /as many good reps as you can/,
    );
  });

  it('falls back to the number of sets', () => {
    expect(formatTarget(exercise({ reps_min: null, reps_max: null, sets: 1 }))).toBe('1 set');
  });
});

describe('formatDetails', () => {
  it('lists rest, warm-up sets, effort and reps in reserve', () => {
    expect(
      formatDetails(exercise({ practice_sets: 2, reps_in_reserve: 2, rest_seconds: 120 })),
    ).toBe('rest 2 min · 2 light warm-up sets first · stop with 2 in the tank');
    expect(formatDetails(exercise({ rest_seconds: 0, effort: 7 }))).toBe('effort 7/10');
  });
});

describe('groupByWeek', () => {
  it('groups the queue by week, in queue order', () => {
    const groups = groupByWeek([workout(3, 2), workout(1, 1), workout(2, 1)]);

    expect(groups.map((g) => [g.week, g.workouts.map((w) => w.position)])).toEqual([
      [1, [1, 2]],
      [2, [3]],
    ]);
  });
});

describe('labels', () => {
  it('names routines and statuses', () => {
    expect(routineLabel('push_pull_legs')).toBe('Push pull legs');
    expect(statusLabel('done')).toBe('Done');
    expect(statusLabel('pending')).toBe('');
  });
});

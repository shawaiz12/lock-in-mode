/** Small, readable workouts for tests, shaped like the real ones the API builds
 * (checked against generated plans: straight sets, supersets, circuits, HIIT, cardio). */
import type { ExerciseDetail, PlannedExercise, WorkoutDetail } from '@/api/endpoints';

/** One planned exercise. Defaults: 3 × 8–12, rest 90 s, strength. */
export function row(id: string, name: string, overrides: Partial<PlannedExercise> = {}): PlannedExercise {
  return {
    id,
    exercise: { id: `x-${id}`, slug: id, name, difficulty: 2 },
    sets: 3,
    reps_min: 8,
    reps_max: 12,
    seconds: null,
    rest_seconds: 90,
    reps_in_reserve: 2,
    effort: null,
    group: 0,
    practice_sets: 0,
    is_test: false,
    swapped_out: false,
    weight_kg: null,
    last: null,
    ...overrides,
  };
}

/** A timed move: warm-up, cool-down, HIIT. Default 30 s, no rest. */
export function timed(id: string, name: string, overrides: Partial<PlannedExercise> = {}): PlannedExercise {
  return row(id, name, {
    sets: 1,
    reps_min: null,
    reps_max: null,
    seconds: 30,
    rest_seconds: 0,
    reps_in_reserve: null,
    effort: 2,
    ...overrides,
  });
}

export function workout(parts: Partial<WorkoutDetail> = {}): WorkoutDetail {
  return {
    id: 'w1',
    position: 1,
    week: 1,
    kind: 'full_body',
    title: 'Full body A',
    format: 'straight_sets',
    recovery: false,
    total_minutes: 30,
    status: 'pending',
    comeback_week: null,
    plan_id: 'plan-1',
    main_minutes: 20,
    warm_up: [],
    main: [],
    finisher: [],
    cool_down: [],
    ...parts,
  };
}

export function detail(id: string, overrides: Partial<ExerciseDetail> = {}): ExerciseDetail {
  return {
    id,
    slug: id,
    name: id,
    category: 'strength',
    movement_slot: 'horizontal_push',
    primary_muscle: null,
    equipment: [],
    also_needs: null,
    difficulty: 2,
    impact: 'none',
    is_timed: false,
    demo_url: null,
    cautions: [],
    exercise_type: 'compound',
    secondary_muscles: [],
    targets: [],
    not_suitable_for: [],
    steps: ['Start in position.', 'Move with control.', 'Return.'],
    cues: ['Brace your core.'],
    common_mistake: 'Rushing the reps.',
    easier: null,
    harder: null,
    alternatives: [],
    ...overrides,
  } as ExerciseDetail;
}

export const notTimed = () => false;

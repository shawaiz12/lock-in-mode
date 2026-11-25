/**
 * Words for the finish screen: what the strength test decided, what moved up or back,
 * the HIIT timing. Plain, specific, never shaming (brief 3.6). Pure (result.test.ts).
 */
import type { components } from '@/api/schema';
import { formatSeconds } from '@/features/plan/format';

type Schemas = components['schemas'];
export type SessionResult = Schemas['SessionResult'];
export type Progress = Schemas['Progress'];
export type Placement = Schemas['Placement'];
export type IntervalProgress = Schemas['IntervalProgress'];
type MovementSlot = Schemas['MovementSlot'];
type BodyLimit = Schemas['BodyLimit'];

const TESTS: Partial<Record<MovementSlot, string>> = {
  horizontal_push: 'Push-ups',
  squat: 'Squats',
  brace: 'Plank',
  vertical_pull: 'Pull-ups',
};

/** "Push-ups: 3 → you start on Knee push-up". */
export function placementLine(placement: Placement): string {
  const test = TESTS[placement.movement] ?? placement.exercise.name;
  const result =
    placement.unit === 'seconds'
      ? formatSeconds(placement.result)
      : `${placement.result} ${placement.result === 1 ? 'rep' : 'reps'}`;
  return `${test}: ${result} → you start on ${placement.exercise.name}`;
}

/** "Goblet squat: 14.5 kg next time". Moving back is said as calmly as moving up. */
export function progressLine(progress: Progress): string {
  const name = progress.exercise.name;
  const weight = progress.weight_kg === null ? '' : ` (${progress.weight_kg} kg)`;
  const hold = progress.seconds === null ? '' : `: hold ${formatSeconds(progress.seconds)}`;
  switch (progress.change) {
    case 'heavier':
      return `${name}: ${progress.weight_kg ?? 'more'} kg next time`;
    case 'extra_set':
      return `${name}: one more set next time`;
    case 'longer_hold':
      return `${name}${hold || ': a longer hold'} next time`;
    case 'harder_move':
      return `${name}: ready for a harder version`;
    case 'more_reps':
      return `${name}: aim for 2 more reps next time`;
    case 'lighter':
      return `${name}: a little lighter next time${weight}`;
    case 'fewer_sets':
      return `${name}: one set fewer next time`;
    case 'shorter_hold':
      return `${name}${hold || ': a shorter hold'} next time`;
    case 'easier_move':
      return `${name}: an easier version next time`;
  }
}

export function isStepUp(progress: Progress): boolean {
  return ['heavier', 'extra_set', 'longer_hold', 'harder_move', 'more_reps'].includes(progress.change);
}

/** "HIIT steps up: 35 s on, 25 s off next time". */
export function intervalsLine(intervals: IntervalProgress): string {
  const timing = `${intervals.work_seconds} s on, ${intervals.rest_seconds} s off next time`;
  return intervals.direction === 'up' ? `HIIT steps up: ${timing}` : `HIIT eases off: ${timing}`;
}

const LIMITS: Record<BodyLimit, string> = {
  knees: 'knees',
  back: 'back',
  shoulders: 'shoulders',
};

/** The offer after a "where does it hurt" answer (ADR 0020 decision 3). */
export function limitQuestion(limit: BodyLimit): string {
  return `Go easy on your ${LIMITS[limit]} in every workout?`;
}

/** The heading: finishing early still counts (brief principle 4: no shame). */
export function finishTitle(done: number, total: number): string {
  if (total > 0 && done >= total) return 'Workout done';
  if (done === 0) return 'Ending here?';
  return 'Done for today?';
}

export function finishSubtitle(done: number, total: number): string {
  if (total > 0 && done >= total) return `Every set: ${done} of ${total}.`;
  if (done === 0) return 'Nothing logged yet. It still moves your plan on.';
  return `${done} of ${total} sets. Half a workout counts.`;
}

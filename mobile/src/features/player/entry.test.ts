import { detail, row, timed, workout } from '@/test/fixtures';

import {
  entryText,
  isReady,
  isWeighted,
  prefill,
  step,
  suggestedWeight,
  targetText,
  toSetLog,
  weightStep,
} from './entry';
import { buildStations, type Item } from './steps';

/** The first real item of a one-exercise workout. */
function first(exercise = row('a', 'Bench'), isTimed = (_: string) => false): Item {
  const [station] = buildStations(workout({ main: [exercise] }), isTimed);
  return station!.items.find((it) => it.kind !== 'practice')!;
}

const last = (reps: number | null, weight_kg: number | null, seconds: number | null = null) => ({
  reps,
  weight_kg,
  seconds,
  logged_at: '2026-11-20T10:00:00Z',
});

describe('prefill', () => {
  it('no history: the bottom of the range, no weight yet', () => {
    expect(prefill(first(row('a', 'Bench', { reps_min: 8, reps_max: 12 })), true)).toEqual({
      reps: 8,
      weight_kg: null,
      seconds: null,
    });
  });

  it('same weight as last time: last time’s reps, kept inside today’s range', () => {
    const r = row('a', 'Bench', { reps_min: 8, reps_max: 12, weight_kg: 40, last: last(10, 40) });
    expect(prefill(first(r), true)).toEqual({ reps: 10, weight_kg: 40, seconds: null });

    const over = row('a', 'Bench', { reps_min: 8, reps_max: 12, weight_kg: 40, last: last(15, 40) });
    expect(prefill(first(over), true).reps).toBe(12);
  });

  it('a new suggested weight (progression went up) starts at the bottom again', () => {
    const r = row('a', 'Bench', { reps_min: 8, reps_max: 12, weight_kg: 42.5, last: last(12, 40) });

    expect(prefill(first(r), true)).toEqual({ reps: 8, weight_kg: 42.5, seconds: null });
  });

  it('no suggested weight: last time’s weight carries forward (gym strength test result)', () => {
    const r = row('a', 'Leg press', { weight_kg: null, last: last(10, 80) });

    expect(suggestedWeight(r)).toBe(80);
    expect(prefill(first(r), true).weight_kg).toBe(80);
  });

  it('bodyweight moves never get a weight', () => {
    const r = row('a', 'Push-up', { last: last(10, null) });

    expect(prefill(first(r), false)).toEqual({ reps: 10, weight_kg: null, seconds: null });
  });

  it('timed moves: the planned seconds', () => {
    expect(prefill(first(timed('a', 'Plank', { seconds: 45 })), false)).toEqual({
      reps: null,
      weight_kg: null,
      seconds: 45,
    });
  });

  it('strength test sets: nothing pre-filled, they say how many', () => {
    const test = row('a', 'Push-up', { reps_min: null, reps_max: null, is_test: true, last: last(20, null) });

    expect(prefill(first(test), false)).toEqual({ reps: null, weight_kg: null, seconds: null });
  });
});

describe('isReady', () => {
  it('needs a count for reps, seconds for holds; never a weight', () => {
    const reps = first();
    const hold = first(row('a', 'Plank', { reps_min: null, reps_max: null, is_test: true }), () => true);

    expect(isReady(reps, { reps: null, weight_kg: 20, seconds: null })).toBe(false);
    expect(isReady(reps, { reps: 8, weight_kg: null, seconds: null })).toBe(true);
    expect(isReady(hold, { reps: null, weight_kg: null, seconds: 0 })).toBe(false);
    expect(isReady(hold, { reps: null, weight_kg: null, seconds: 42 })).toBe(true);
  });
});

describe('weights', () => {
  it('dumbbells or gym kit = weighted', () => {
    expect(isWeighted(detail('a', { equipment: ['dumbbells'] }))).toBe(true);
    expect(isWeighted(detail('a', { equipment: ['gym'] }))).toBe(true);
    expect(isWeighted(detail('a', { equipment: ['pull_up_bar'] }))).toBe(false);
    expect(isWeighted(detail('a', { equipment: [] }))).toBe(false);
    expect(isWeighted(undefined)).toBe(false);
  });

  it('steps like a real gym, the same as progression', () => {
    expect(weightStep(detail('a', { equipment: ['dumbbells'], movement_slot: 'squat' }))).toBe(2.5);
    expect(weightStep(detail('a', { equipment: ['gym'], also_needs: 'Kettlebell' }))).toBe(4);
    expect(weightStep(detail('a', { equipment: ['gym'], also_needs: 'Barbell and rack', movement_slot: 'squat' }))).toBe(5);
    expect(weightStep(detail('a', { equipment: ['gym'], also_needs: 'Barbell, bench', movement_slot: 'horizontal_push' }))).toBe(2.5);
    expect(weightStep(detail('a', { equipment: ['gym'], also_needs: 'Cable machine' }))).toBe(5);
    expect(weightStep(undefined)).toBe(2.5);
  });

  it('− / + never go below zero and keep half kilos', () => {
    expect(step(null, 1, 8)).toBe(9);
    expect(step(2.5, -5)).toBe(0);
    expect(step(20, 2.5)).toBe(22.5);
    expect(step(10.3, 0)).toBe(10.5);
  });
});

describe('words', () => {
  it('says the target plainly', () => {
    expect(targetText(first(row('a', 'Bench', { reps_min: 8, reps_max: 12 })))).toBe('8–12 reps');
    expect(targetText(first(row('a', 'Bench', { reps_min: 10, reps_max: 10 })))).toBe('10 reps');
    expect(targetText(first(timed('a', 'Walk', { seconds: 1380 })))).toBe('23 min');
    expect(targetText(first(row('a', 'Push-up', { reps_min: null, reps_max: null, is_test: true })))).toMatch(
      /As many good reps/,
    );
  });

  it('says what one tap will log', () => {
    expect(entryText({ reps: 10, weight_kg: 20, seconds: null })).toBe('10 reps · 20 kg');
    expect(entryText({ reps: 1, weight_kg: null, seconds: null })).toBe('1 rep');
    expect(entryText({ reps: null, weight_kg: null, seconds: 90 })).toBe('1 min 30 s');
  });

  it('sends exactly the numbers', () => {
    expect(toSetLog({ reps: 10, weight_kg: null, seconds: null })).toEqual({ reps: 10, weight_kg: null, seconds: null });
  });
});

import { row, workout } from '@/test/fixtures';

import {
  finishSubtitle,
  finishTitle,
  intervalsLine,
  isStepUp,
  limitQuestion,
  placementLine,
  type Progress,
  progressLine,
} from './result';
import { buildStations } from './steps';
import { coachLine, partLabel, setLabel, upNext } from './words';

const ref = (name: string) => ({ id: name, slug: name, name, difficulty: 2 });
const change = (c: Progress['change'], extra: Partial<Progress> = {}): Progress => ({
  exercise: ref('Goblet squat'),
  change: c,
  weight_kg: null,
  seconds: null,
  set_change: 0,
  ...extra,
});

describe('finish screen words', () => {
  it('says what the strength test decided', () => {
    expect(
      placementLine({ movement: 'horizontal_push', result: 3, unit: 'reps', exercise: ref('Knee push-up') }),
    ).toBe('Push-ups: 3 reps → you start on Knee push-up');
    expect(placementLine({ movement: 'brace', result: 45, unit: 'seconds', exercise: ref('Plank') })).toBe(
      'Plank: 45 s → you start on Plank',
    );
  });

  it('says every kind of change plainly', () => {
    expect(progressLine(change('heavier', { weight_kg: 14.5 }))).toBe('Goblet squat: 14.5 kg next time');
    expect(progressLine(change('extra_set'))).toBe('Goblet squat: one more set next time');
    expect(progressLine(change('longer_hold', { seconds: 50 }))).toBe('Goblet squat: hold 50 s next time');
    expect(progressLine(change('harder_move'))).toBe('Goblet squat: ready for a harder version');
    expect(progressLine(change('more_reps'))).toBe('Goblet squat: aim for 2 more reps next time');
    expect(progressLine(change('lighter', { weight_kg: 12 }))).toBe('Goblet squat: a little lighter next time (12 kg)');
    expect(progressLine(change('fewer_sets'))).toBe('Goblet squat: one set fewer next time');
    expect(progressLine(change('shorter_hold', { seconds: 30 }))).toBe('Goblet squat: hold 30 s next time');
    expect(progressLine(change('easier_move'))).toBe('Goblet squat: an easier version next time');
  });

  it('splits steps up from steps back', () => {
    expect(isStepUp(change('heavier'))).toBe(true);
    expect(isStepUp(change('more_reps'))).toBe(true);
    expect(isStepUp(change('lighter'))).toBe(false);
    expect(isStepUp(change('easier_move'))).toBe(false);
  });

  it('says the HIIT timing', () => {
    expect(intervalsLine({ direction: 'up', work_seconds: 35, rest_seconds: 25 })).toBe(
      'HIIT steps up: 35 s on, 25 s off next time',
    );
    expect(intervalsLine({ direction: 'down', work_seconds: 25, rest_seconds: 35 })).toMatch(/^HIIT eases off/);
  });

  it('never shames an early finish', () => {
    expect(finishTitle(10, 10)).toBe('Workout done');
    expect(finishTitle(4, 10)).toBe('Done for today?');
    expect(finishSubtitle(4, 10)).toBe('4 of 10 sets. Half a workout counts.');
    expect(finishTitle(0, 10)).toBe('Ending here?');
  });

  it('asks about a limit in plain words', () => {
    expect(limitQuestion('knees')).toBe('Go easy on your knees in every workout?');
  });
});

describe('player labels', () => {
  it('names sets, rounds and warm-up sets', () => {
    const [single] = buildStations(workout({ main: [row('a', 'Bench', { sets: 3, practice_sets: 1 })] }), () => false);
    const [circuit] = buildStations(
      workout({ format: 'circuit', main: [row('a', 'Squat', { sets: 2 }), row('b', 'Row', { sets: 2 })] }),
      () => false,
    );

    expect(setLabel(single!.items[0]!, single!)).toBe('Warm-up set 1 of 1');
    expect(setLabel(single!.items[2]!, single!)).toBe('Set 2 of 3');
    expect(setLabel(circuit!.items[2]!, circuit!)).toBe('Round 2 of 2');
    expect(upNext(single!.items[2]!, single!)).toBe('Up next: Bench · set 2 of 3');
    expect(partLabel('cool_down')).toBe('Cool-down');
  });

  it('gives one coaching line in plain words', () => {
    const [s] = buildStations(workout({ main: [row('a', 'Bench', { reps_in_reserve: 2 })] }), () => false);
    const [t] = buildStations(workout({ main: [row('a', 'Leg press', { is_test: true })] }), () => false);
    const [h] = buildStations(
      workout({ main: [row('a', 'Burpee', { reps_min: null, reps_max: null, seconds: 30, reps_in_reserve: null, effort: 8 })] }),
      () => false,
    );

    expect(coachLine(s!.items[0]!)).toBe('Stop when you could still do 2 more good reps.');
    expect(coachLine(t!.items[0]!)).toMatch(/pick a weight you could lift about 3 more times/);
    expect(coachLine(h!.items[0]!)).toBe('Effort 8 of 10.');
  });
});

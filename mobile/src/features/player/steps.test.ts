import { notTimed, row, timed, workout } from '@/test/fixtures';

import { buildStations, CIRCUIT_ROUND_REST, isDone, loggedKeys, nextPosition, progress } from './steps';

/** "<name> s<set> r<rest>" per item: the whole order of a station in one readable line. */
const plan = (items: { exercise: { exercise: { name: string } }; set: number; restAfter: number; kind: string }[]) =>
  items.map((it) => `${it.exercise.exercise.name}${it.kind === 'practice' ? ' p' : ' s'}${it.set} r${it.restAfter}`);

describe('buildStations', () => {
  it('puts warm-up, each exercise, and cool-down on their own screens, in order', () => {
    const w = workout({
      warm_up: [timed('wu1', 'March'), timed('wu2', 'Arm circles')],
      main: [row('a', 'Leg press', { group: 0 }), row('b', 'Chest press', { group: 1 })],
      cool_down: [timed('cd1', 'Child pose')],
    });

    const stations = buildStations(w, notTimed);

    expect(stations.map((s) => [s.part, s.layout, s.title])).toEqual([
      ['warm_up', 'sequence', 'Warm-up'],
      ['main', 'single', 'Leg press'],
      ['main', 'single', 'Chest press'],
      ['cool_down', 'sequence', 'Cool-down'],
    ]);
  });

  it('straight sets: rest after every set, also before the next exercise, never before the cool-down', () => {
    const w = workout({
      main: [row('a', 'Squat', { sets: 2, rest_seconds: 150, group: 0 }), row('b', 'Row', { sets: 2, rest_seconds: 90, group: 1 })],
      cool_down: [timed('cd', 'Stretch')],
    });

    const [squat, rowing] = buildStations(w, notTimed);

    expect(plan(squat!.items)).toEqual(['Squat s1 r150', 'Squat s2 r150']);
    expect(plan(rowing!.items)).toEqual(['Row s1 r90', 'Row s2 r0']);
  });

  it('practice sets come first, are never sent, and rest nothing', () => {
    const w = workout({ main: [row('a', 'Bench', { sets: 2, practice_sets: 2, rest_seconds: 120 })] });

    const [bench] = buildStations(w, notTimed);

    expect(plan(bench!.items)).toEqual(['Bench p1 r0', 'Bench p2 r0', 'Bench s1 r120', 'Bench s2 r0']);
    expect(bench!.items[0]!.key).toBe('a/p1');
    expect(bench!.items[2]!.key).toBe('a/1');
  });

  it('a superset goes A, B, rest; uneven sets drop out; the rest is the longest of the round', () => {
    // A real 30-minute session: row 4 × 3–6 (rest 150) paired with shoulder press 2 × 8–12 (rest 75).
    const w = workout({
      format: 'first_straight_then_supersets',
      main: [
        row('a', 'Bench', { group: 0, sets: 4, rest_seconds: 150 }),
        row('b', 'Row', { group: 1, sets: 4, rest_seconds: 150 }),
        row('c', 'Press', { group: 1, sets: 2, rest_seconds: 75 }),
      ],
    });

    const [first, pair] = buildStations(w, notTimed);

    expect(first!.layout).toBe('single');
    expect(pair!.layout).toBe('superset');
    expect(pair!.title).toBe('Superset');
    expect(plan(pair!.items)).toEqual([
      'Row s1 r0',
      'Press s1 r150',
      'Row s2 r0',
      'Press s2 r150',
      'Row s3 r150',
      'Row s4 r0',
    ]);
  });

  it('a circuit goes round by round, rests between moves, and at least a minute between rounds', () => {
    const w = workout({
      format: 'circuit',
      main: [
        row('a', 'Squat', { sets: 2, rest_seconds: 30 }),
        row('b', 'Push-up', { sets: 2, rest_seconds: 30 }),
      ],
      cool_down: [timed('cd', 'Stretch')],
    });

    const [circuit] = buildStations(w, notTimed);

    expect(circuit!.layout).toBe('circuit');
    expect(plan(circuit!.items)).toEqual([
      'Squat s1 r30',
      `Push-up s1 r${CIRCUIT_ROUND_REST}`,
      'Squat s2 r30',
      'Push-up s2 r0',
    ]);
    expect(circuit!.items.map((it) => it.round)).toEqual([1, 1, 2, 2]);
  });

  it('10-minute circuits (no rest between moves) still rest between rounds', () => {
    const w = workout({
      format: 'circuit',
      main: [row('a', 'Squat', { sets: 2, rest_seconds: 0 }), row('b', 'Push-up', { sets: 2, rest_seconds: 0 })],
    });

    const [circuit] = buildStations(w, notTimed);

    expect(plan(circuit!.items)).toEqual(['Squat s1 r0', `Push-up s1 r${CIRCUIT_ROUND_REST}`, 'Squat s2 r0', 'Push-up s2 r0']);
  });

  it('HIIT runs by itself: work, rest, next move, round after round, no rest at the very end', () => {
    const w = workout({
      format: 'intervals',
      kind: 'hiit',
      main: [
        timed('a', 'Squat jump', { sets: 2, seconds: 30, rest_seconds: 30 }),
        timed('b', 'High knees', { sets: 2, seconds: 30, rest_seconds: 30 }),
      ],
    });

    const [hiit] = buildStations(w, notTimed);

    expect(hiit!.title).toBe('HIIT');
    expect(hiit!.items.every((it) => it.kind === 'timed' && it.autoNext)).toBe(true);
    expect(plan(hiit!.items)).toEqual(['Squat jump s1 r30', 'High knees s1 r30', 'Squat jump s2 r30', 'High knees s2 r0']);
  });

  it('a finisher after strength work is its own HIIT-style screen, rested into', () => {
    const w = workout({
      format: 'supersets',
      main: [row('a', 'Squat', { sets: 1, rest_seconds: 60 })],
      finisher: [timed('f1', 'Inchworm', { sets: 2, seconds: 20, rest_seconds: 40 })],
      cool_down: [timed('cd', 'Stretch')],
    });

    const stations = buildStations(w, notTimed);

    expect(stations.map((s) => s.title)).toEqual(['Squat', 'Finisher', 'Cool-down']);
    expect(plan(stations[0]!.items)).toEqual(['Squat s1 r60']); // rest before the finisher
    expect(plan(stations[1]!.items)).toEqual(['Inchworm s1 r40', 'Inchworm s2 r0']);
  });

  it('steady cardio is one long timer, started by hand', () => {
    const w = workout({ format: 'continuous', main: [timed('a', 'Brisk walk', { seconds: 1380, effort: 5 })] });

    const [walk] = buildStations(w, notTimed);

    expect(walk!.layout).toBe('single');
    expect(walk!.items).toHaveLength(1);
    expect(walk!.items[0]).toMatchObject({ kind: 'timed', autoNext: false });
  });

  it('warm-up moves chain by themselves; a warm-up move with reps waits for a tap', () => {
    const w = workout({
      warm_up: [timed('a', 'March', { seconds: 90 }), row('b', 'Glute bridge', { sets: 1, rest_seconds: 0 })],
    });

    const [warmUp] = buildStations(w, notTimed);

    expect(warmUp!.items.map((it) => [it.kind, it.autoNext])).toEqual([
      ['timed', true],
      ['reps', false],
    ]);
  });

  it('open strength-test sets: a hold uses the library to know it is timed', () => {
    const w = workout({
      format: 'circuit',
      main: [
        row('a', 'Push-up', { sets: 1, reps_min: null, reps_max: null, is_test: true }),
        row('b', 'Plank', { sets: 1, reps_min: null, reps_max: null, is_test: true }),
      ],
    });

    const [circuit] = buildStations(w, (id) => id === 'x-b');

    expect(circuit!.items.map((it) => it.kind)).toEqual(['open_reps', 'open_hold']);
  });

  it('leaves out rows swapped out mid-workout (their sets are already history)', () => {
    const w = workout({
      main: [
        row('old', 'Lunge', { sets: 1, swapped_out: true, group: 0 }),
        row('new', 'Split squat', { sets: 2, group: 0 }),
      ],
    });

    const stations = buildStations(w, notTimed);

    expect(stations).toHaveLength(1);
    expect(stations[0]!.title).toBe('Split squat');
  });

  it('a workout with nothing in it has no stations', () => {
    expect(buildStations(workout(), notTimed)).toEqual([]);
  });
});

describe('where you are', () => {
  const w = workout({
    warm_up: [timed('wu', 'March')],
    main: [row('a', 'Bench', { sets: 2, practice_sets: 1, group: 0 }), row('b', 'Row', { sets: 2, group: 1 })],
  });
  const stations = buildStations(w, notTimed);
  const none = new Set<string>();

  it('starts at the very first item', () => {
    expect(nextPosition(stations, none, none, none)).toEqual({ station: 0, item: 0 });
  });

  it('continues at the first set not logged (coming back to an open workout)', () => {
    const logged = loggedKeys([
      { planned_exercise_id: 'wu', set_number: 1 },
      { planned_exercise_id: 'a', set_number: 1 },
    ]);

    // Bench practice set counts as done: its first real set is logged.
    expect(nextPosition(stations, logged, none, none)).toEqual({ station: 1, item: 2 });
  });

  it('a practice set ticked on this phone is done', () => {
    const logged = loggedKeys([{ planned_exercise_id: 'wu', set_number: 1 }]);
    const local = new Set(['a/p1']);

    expect(nextPosition(stations, logged, local, none)).toEqual({ station: 1, item: 1 });
    expect(isDone(stations[1]!.items[0]!, logged, local)).toBe(true);
  });

  it('a skipped exercise is passed over; a passed-over move counts as done here only', () => {
    const logged = loggedKeys([{ planned_exercise_id: 'wu', set_number: 1 }]);

    expect(nextPosition(stations, logged, none, new Set([stations[1]!.key]))).toEqual({ station: 2, item: 0 });
    expect(nextPosition(stations, none, new Set(['wu/1']), none)).toEqual({ station: 1, item: 0 });
  });

  it('nothing left: null (time for the finish screen)', () => {
    const all = new Set(stations.flatMap((s) => s.items.map((it) => it.key)));

    expect(nextPosition(stations, all, none, none)).toBeNull();
    expect(nextPosition(stations, none, none, new Set(stations.map((s) => s.key)))).toBeNull();
  });

  it('progress counts real sets only', () => {
    const logged = loggedKeys([
      { planned_exercise_id: 'wu', set_number: 1 },
      { planned_exercise_id: 'a', set_number: 1 },
    ]);

    expect(progress(stations, logged)).toEqual({ done: 2, total: 5 });
  });
});

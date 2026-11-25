/**
 * A workout, turned into what the player shows: screens ("stations") and, on each, the
 * sets to do in order ("items"). Pure: no React, no network, so every rule is tested on
 * its own (steps.test.ts). .NET: a plain domain service, like a builder class.
 *
 * One station per screen (his choice, ADR 0032):
 *   warm-up            one screen, its moves run one after another by themselves
 *   straight sets      one screen per exercise: set, rest, set, rest
 *   superset           one screen for the pair: A, B, rest, A, B, rest
 *   circuit            one screen for the round: every move in a row, then the next round
 *   HIIT / finisher    one screen, a timer: work, rest, next move, round after round
 *   steady cardio      one screen, one long timer
 *   cool-down          one screen, like the warm-up
 *
 * The server's time estimate (training/sessions.py `estimate_seconds`) is the source of
 * these rules: a superset shares its rest, a circuit rests between moves and 60 s between
 * rounds, intervals are work then rest per move.
 */
import type { PlannedExercise, WorkoutDetail } from '@/api/endpoints';

export type Part = 'warm_up' | 'main' | 'finisher' | 'cool_down';

/**
 * reps:      "8–12 reps": one tap logs the pre-filled numbers
 * timed:     "30 s": a countdown, logged when it ends (or when stopped early)
 * open_reps: strength test, "as many good reps as you can": they say how many
 * open_hold: strength test hold (plank): a stopwatch, logged when they stop
 * practice:  a light warm-up set before the first real set: ticked, never sent
 */
export type ItemKind = 'reps' | 'timed' | 'open_reps' | 'open_hold' | 'practice';

export type Item = {
  /** "<planned exercise id>/<set>" for real sets, "<id>/p<n>" for practice sets. */
  key: string;
  exercise: PlannedExercise;
  part: Part;
  /** The set number sent to the API (practice sets: their own count, never sent). */
  set: number;
  /** Real sets of this exercise (the "of 3" in "Set 2 of 3"). */
  sets: number;
  kind: ItemKind;
  /** Seconds of rest after this item. 0: straight on to the next. */
  restAfter: number;
  /** A timed item that starts by itself once the one before it (and its rest) is over:
   * warm-up, cool-down, HIIT and finisher moves. One "Start" runs the whole station. */
  autoNext: boolean;
  /** Circuits, intervals, supersets: which round this item is in. */
  round: number;
  rounds: number;
};

export type Layout = 'single' | 'superset' | 'circuit' | 'intervals' | 'sequence';

export type Station = {
  key: string;
  part: Part;
  layout: Layout;
  title: string;
  /** The exercises on this screen, in order (for "How to do it" and swaps). */
  exercises: PlannedExercise[];
  items: Item[];
};

/** Rest between circuit rounds: training/sessions.py CIRCUIT_ROUND_REST. */
export const CIRCUIT_ROUND_REST = 60;

const PARTS: Part[] = ['warm_up', 'main', 'finisher', 'cool_down'];
const WORKING_PARTS: ReadonlySet<Part> = new Set<Part>(['main', 'finisher']);

/** Is this exercise a hold (plank) or a timed move? From the exercise library
 * (GET /exercises/{id} `is_timed`); undefined while it isn't loaded. */
export type IsTimed = (exerciseId: string) => boolean | undefined;

export function kindOf(exercise: PlannedExercise, isTimed: IsTimed): Exclude<ItemKind, 'practice'> {
  if (exercise.seconds !== null) return 'timed';
  if (exercise.reps_min !== null) return 'reps';
  // An open test set: no target at all. A hold is timed with a stopwatch.
  return isTimed(exercise.exercise.id) ? 'open_hold' : 'open_reps';
}

function rowsOf(workout: WorkoutDetail, part: Part): PlannedExercise[] {
  // Rows swapped out mid-workout keep the sets already logged, and a new row after them
  // has the sets that were left (ADR 0020): the old row is history, not a station.
  return workout[part].filter((row) => !row.swapped_out);
}

function item(
  row: PlannedExercise,
  part: Part,
  set: number,
  kind: ItemKind,
  restAfter: number,
  autoNext: boolean,
  round: number,
  rounds: number,
): Item {
  const key = kind === 'practice' ? `${row.id}/p${set}` : `${row.id}/${set}`;
  return { key, exercise: row, part, set, sets: row.sets, kind, restAfter, autoNext, round, rounds };
}

/** Moves one after another, each of its sets in turn (warm-up, cool-down, mobility). */
function sequence(rows: PlannedExercise[], part: Part, title: string, isTimed: IsTimed): Station {
  const items: Item[] = [];
  for (const row of rows) {
    const kind = kindOf(row, isTimed);
    for (let set = 1; set <= row.sets; set++) {
      items.push(item(row, part, set, kind, row.rest_seconds, kind === 'timed', set, row.sets));
    }
  }
  return { key: `${part}:sequence`, part, layout: 'sequence', title, exercises: rows, items };
}

/** Round after round: every move once per round (circuits, intervals). */
function rounds(
  rows: PlannedExercise[],
  part: Part,
  layout: 'circuit' | 'intervals',
  title: string,
  isTimed: IsTimed,
): Station {
  const total = Math.max(...rows.map((row) => row.sets));
  const items: Item[] = [];
  for (let round = 1; round <= total; round++) {
    const inRound = rows.filter((row) => row.sets >= round);
    inRound.forEach((row, index) => {
      const kind = kindOf(row, isTimed);
      const lastInRound = index === inRound.length - 1;
      let rest = row.rest_seconds;
      if (layout === 'circuit' && lastInRound && round < total) {
        rest = Math.max(rest, CIRCUIT_ROUND_REST);
      }
      const auto = layout === 'intervals' && kind === 'timed';
      items.push(item(row, part, round, kind, rest, auto, round, total));
    });
  }
  return { key: `${part}:${layout}`, part, layout, title, exercises: rows, items };
}

/** One exercise alone, or a superset pair: practice sets first, then the rounds. A pair
 * goes A, B, rest: the rest after the round is the longest of the two. */
function group(rows: PlannedExercise[], part: Part, isTimed: IsTimed): Station {
  const items: Item[] = [];
  const total = Math.max(...rows.map((row) => row.sets));
  for (const row of rows) {
    for (let n = 1; n <= row.practice_sets; n++) {
      items.push(item(row, part, n, 'practice', 0, false, 0, total));
    }
  }
  for (let round = 1; round <= total; round++) {
    const inRound = rows.filter((row) => row.sets >= round);
    const roundRest = Math.max(...inRound.map((row) => row.rest_seconds));
    inRound.forEach((row, index) => {
      const rest = index === inRound.length - 1 ? roundRest : 0;
      items.push(item(row, part, round, kindOf(row, isTimed), rest, false, round, total));
    });
  }
  const first = rows[0];
  const single = rows.length === 1 && first !== undefined;
  return {
    key: `${part}:${rows.map((row) => row.id).join('+')}`,
    part,
    layout: single ? 'single' : 'superset',
    title: single ? first.exercise.name : 'Superset',
    exercises: rows,
    items,
  };
}

/** Rows with the same `group`, in the order the groups first appear. */
function byGroup(rows: PlannedExercise[]): PlannedExercise[][] {
  const groups = new Map<number, PlannedExercise[]>();
  for (const row of rows) {
    const members = groups.get(row.group) ?? [];
    members.push(row);
    groups.set(row.group, members);
  }
  return [...groups.values()];
}

function mainStations(workout: WorkoutDetail, isTimed: IsTimed): Station[] {
  const rows = rowsOf(workout, 'main');
  if (rows.length === 0) return [];
  switch (workout.format) {
    case 'intervals':
      return [rounds(rows, 'main', 'intervals', 'HIIT', isTimed)];
    case 'circuit':
      return [rounds(rows, 'main', 'circuit', 'Circuit', isTimed)];
    case 'flow':
      return [sequence(rows, 'main', workout.title, isTimed)];
    case 'continuous':
      return rows.map((row) => ({ ...group([row], 'main', isTimed), layout: 'single' as const }));
    default:
      return byGroup(rows).map((members) => group(members, 'main', isTimed));
  }
}

/** Every screen of the workout, in the order it's done. */
export function buildStations(workout: WorkoutDetail, isTimed: IsTimed): Station[] {
  const stations: Station[] = [];
  for (const part of PARTS) {
    const rows = rowsOf(workout, part);
    if (rows.length === 0) continue;
    if (part === 'main') stations.push(...mainStations(workout, isTimed));
    else if (part === 'finisher') stations.push(rounds(rows, part, 'intervals', 'Finisher', isTimed));
    else stations.push(sequence(rows, part, part === 'warm_up' ? 'Warm-up' : 'Cool-down', isTimed));
  }
  // The last item of a screen rests only when hard work follows (the next exercise,
  // the finisher): no rest before the cool-down or at the very end.
  stations.forEach((station, index) => {
    const last = station.items[station.items.length - 1];
    const next = stations[index + 1];
    const workFollows =
      next !== undefined && WORKING_PARTS.has(next.part) && WORKING_PARTS.has(station.part);
    if (last && !workFollows) station.items[station.items.length - 1] = { ...last, restAfter: 0 };
  });
  return stations;
}

/** Real sets the server has, as item keys ("<planned exercise id>/<set>"). */
export function loggedKeys(sets: readonly { planned_exercise_id: string; set_number: number }[]): Set<string> {
  return new Set(sets.map((s) => `${s.planned_exercise_id}/${s.set_number}`));
}

/**
 * Is this item done? Real sets: logged on the server, or passed over on this phone
 * ("Skip" on a warm-up move). Practice sets: ticked on this phone, or the exercise's
 * first real set is already logged (continuing a workout doesn't ask for them again).
 */
export function isDone(item: Item, logged: ReadonlySet<string>, localDone: ReadonlySet<string>): boolean {
  if (localDone.has(item.key)) return true;
  if (item.kind !== 'practice') return logged.has(item.key);
  return logged.has(`${item.exercise.id}/1`);
}

export type Position = { station: number; item: number };

/**
 * Where the person is: the first item not done, skipping screens they moved past
 * ("Skip exercise"). null: nothing left, time for the finish screen.
 */
export function nextPosition(
  stations: readonly Station[],
  logged: ReadonlySet<string>,
  localDone: ReadonlySet<string>,
  passed: ReadonlySet<string>,
): Position | null {
  for (let s = 0; s < stations.length; s++) {
    const station = stations[s];
    if (!station || passed.has(station.key)) continue;
    const i = station.items.findIndex((it) => !isDone(it, logged, localDone));
    if (i !== -1) return { station: s, item: i };
  }
  return null;
}

/** How much is done, for the progress bar: real sets only. */
export function progress(stations: readonly Station[], logged: ReadonlySet<string>): { done: number; total: number } {
  let done = 0;
  let total = 0;
  for (const station of stations) {
    for (const it of station.items) {
      if (it.kind === 'practice') continue;
      total += 1;
      if (logged.has(it.key)) done += 1;
    }
  }
  return { done, total };
}

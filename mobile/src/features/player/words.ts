/** Short labels for the player screen. Pure (words.test.ts). */
import type { Item, Layout, Part, Station } from './steps';

const PARTS: Record<Part, string> = {
  warm_up: 'Warm-up',
  main: 'Workout',
  finisher: 'Finisher',
  cool_down: 'Cool-down',
};

export function partLabel(part: Part): string {
  return PARTS[part];
}

const ROUNDS: ReadonlySet<Layout> = new Set<Layout>(['circuit', 'intervals']);

/** "Set 2 of 3", "Round 1 of 3", "Warm-up set 1 of 2". Empty for one-off moves. */
export function setLabel(item: Item, station: Pick<Station, 'layout'>): string {
  if (item.kind === 'practice') {
    return `Warm-up set ${item.set} of ${item.exercise.practice_sets}`;
  }
  if (ROUNDS.has(station.layout)) return `Round ${item.round} of ${item.rounds}`;
  if (item.sets <= 1) return '';
  return `Set ${item.set} of ${item.sets}`;
}

/** The one coaching line under the target, in plain words (brief principle 2). */
export function coachLine(item: Item): string {
  const row = item.exercise;
  if (item.kind === 'practice') return 'Not logged: just getting the movement in.';
  if (row.is_test && item.kind === 'reps') {
    return 'Strength test: pick a weight you could lift about 3 more times.';
  }
  if (row.is_test) return 'Strength test: this sets your starting point.';
  if (row.reps_in_reserve !== null && item.kind === 'reps') {
    const left = row.reps_in_reserve;
    return `Stop when you could still do ${left} more good ${left === 1 ? 'rep' : 'reps'}.`;
  }
  if (row.effort !== null) return `Effort ${row.effort} of 10.`;
  return '';
}

/** "Up next: Push-up · set 2 of 3" during a rest. */
export function upNext(item: Item, station: Pick<Station, 'layout'>): string {
  const label = setLabel(item, station);
  return `Up next: ${item.exercise.exercise.name}${label ? ` · ${label.toLowerCase()}` : ''}`;
}

/** Safety line, always on screen while training (brief 3.1). */
export const SAFETY_LINE = 'Stop if you feel sharp pain, dizziness or chest pain.';

/** Sets ticked offline (ADR 0033): kept on the phone, nothing to fix. */
export function waitingLine(sets: number): string {
  return sets === 1
    ? '1 set is saved on this phone. It syncs when you’re online.'
    : `${sets} sets are saved on this phone. They sync when you’re online.`;
}

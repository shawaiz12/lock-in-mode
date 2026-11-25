/**
 * The numbers for one set: what's pre-filled, what one tap sends, how the − / + buttons
 * step. Pure functions (entry.test.ts).
 *
 * Pre-fill (ADR 0018 "one tap per set, pre-filled", ADR 0032):
 * - weight: the suggested weight (progress, else last time's), else nothing.
 * - reps: what they did last time at that same weight, kept inside today's range; a new
 *   weight (or no last time) starts at the bottom of the range. Never the top by default:
 *   progression steps up when every set hits the top (ADR 0019), so the top must be
 *   something they did, not something they tapped through.
 * - seconds: the planned time. A countdown stopped early logs the seconds really done.
 * - strength test sets: nothing. They say how many (reps) or stop a stopwatch (holds).
 */
import type { PlannedExercise } from '@/api/endpoints';
import type { components } from '@/api/schema';
import { formatSeconds } from '@/features/plan/format';

import type { Item } from './steps';

export type ExerciseDetail = components['schemas']['ExerciseDetail'];
export type SetLogWrite = components['schemas']['SetLogWrite'];

export type Entry = { reps: number | null; weight_kg: number | null; seconds: number | null };

type MovementSlot = components['schemas']['MovementSlot'];

/** training/plan_types.py WEIGHTED_KIT: dumbbells, or kit only a gym has. */
export function isWeighted(detail: Pick<ExerciseDetail, 'equipment'> | undefined): boolean {
  return detail?.equipment.some((kit) => kit === 'dumbbells' || kit === 'gym') ?? false;
}

const LOWER_BODY: ReadonlySet<MovementSlot> = new Set<MovementSlot>([
  'squat',
  'single_leg',
  'hinge',
  'bridge',
  'leg_curl',
  'leg_extension',
  'calves',
  'adductors',
]);
const BARS = ['barbell', 'ez bar', 'trap bar', 'smith'];

/** One press of − / + on the weight: the next weight a real gym has. The same steps as
 * progression (training/progression.py `weight_step`), so both agree. */
export function weightStep(
  detail: Pick<ExerciseDetail, 'equipment' | 'also_needs' | 'movement_slot'> | undefined,
): number {
  if (!detail) return 2.5;
  const lower = LOWER_BODY.has(detail.movement_slot);
  const needs = (detail.also_needs ?? '').toLowerCase();
  if (detail.equipment.includes('dumbbells')) return 2.5;
  if (needs.includes('kettlebell')) return 4;
  if (BARS.some((bar) => needs.includes(bar))) return lower ? 5 : 2.5;
  if (needs.includes('machine') || needs.includes('cable')) return 5;
  return lower ? 5 : 2.5;
}

export function suggestedWeight(row: PlannedExercise): number | null {
  return row.weight_kg ?? row.last?.weight_kg ?? null;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

export function prefill(item: Item, weighted: boolean): Entry {
  const row = item.exercise;
  const weight = weighted ? suggestedWeight(row) : null;
  switch (item.kind) {
    case 'timed':
      return { reps: null, weight_kg: weight, seconds: row.seconds };
    case 'open_reps':
    case 'open_hold':
    case 'practice':
      return { reps: null, weight_kg: weight, seconds: null };
    case 'reps': {
      const low = row.reps_min ?? 1;
      const high = row.reps_max ?? low;
      const last = row.last;
      const sameWeight = last !== null && (last.weight_kg ?? null) === weight;
      const reps = last?.reps != null && sameWeight ? clamp(last.reps, low, high) : low;
      return { reps, weight_kg: weight, seconds: null };
    }
  }
}

/** Can this be ticked as it is? Open test reps need a count; everything else is ready.
 * Weight is never required: "no weight yet" is allowed (ab wheel, bodyweight days). */
export function isReady(item: Item, entry: Entry): boolean {
  if (item.kind === 'open_reps' || item.kind === 'reps') return entry.reps !== null;
  if (item.kind === 'open_hold' || item.kind === 'timed') return entry.seconds !== null && entry.seconds > 0;
  return true;
}

/** The PUT body. Only what applies: reps or seconds, plus the weight when there is one. */
export function toSetLog(entry: Entry): SetLogWrite {
  return { reps: entry.reps, seconds: entry.seconds, weight_kg: entry.weight_kg };
}

/** Adjust one number with − / +, never below zero (weights: rounded to 0.5 kg). */
export function step(value: number | null, by: number, start = 0): number {
  const next = Math.max(0, (value ?? start) + by);
  return Math.round(next * 2) / 2;
}

/** "8–12 reps", "30 s", "As many good reps as you can". What to aim for. */
export function targetText(item: Item): string {
  const row = item.exercise;
  switch (item.kind) {
    case 'open_reps':
      return 'As many good reps as you can, stop with 2 left';
    case 'open_hold':
      return 'Hold as long as you can with good form';
    case 'practice':
      return 'Light warm-up set: easy weight, about 8 smooth reps';
    case 'timed':
      return formatSeconds(row.seconds ?? 0);
    case 'reps':
      if (row.reps_min !== null && row.reps_max !== null && row.reps_min !== row.reps_max) {
        return `${row.reps_min}–${row.reps_max} reps`;
      }
      return `${row.reps_min ?? 0} reps`;
  }
}

/** "10 reps · 20 kg", "45 s". What one tap will log. */
export function entryText(entry: Entry): string {
  const parts: string[] = [];
  if (entry.reps !== null) parts.push(`${entry.reps} ${entry.reps === 1 ? 'rep' : 'reps'}`);
  if (entry.seconds !== null) parts.push(formatSeconds(entry.seconds));
  if (entry.weight_kg !== null) parts.push(`${entry.weight_kg} kg`);
  return parts.join(' · ');
}

/**
 * The Lock In pact's words (ADR 0036): a promise small enough to keep, written from the
 * person's real answers. Pure, no React.
 *
 * Why a pact: committing in your own hand (signing, not just tapping) makes people more
 * likely to follow through, and "If I miss a week, I come back" sets up a comeback, not a
 * failure, from day one (no shame, retention-knowledge.md guardrails).
 */
import type { Profile } from '@/api/endpoints';

/** Workouts that keep a week in the streak (ADR 0034; the server's `keep_at`). */
export const KEEP_AT = 2;

const GOALS: Record<Profile['goal'], string> = {
  build_muscle: 'Build muscle',
  strength: 'Build strength',
  lose_fat: 'Get fit',
  stamina: 'Stamina',
  stay_active: 'Stay active',
};

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const DAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

export function promiseLines(profile: Pick<Profile, 'days_per_week'>): [string, string] {
  return [
    `I train ${profile.days_per_week} days a week. Any week with ${KEEP_AT} workouts counts.`,
    'If I miss a week, I come back.',
  ];
}

/** The three small facts under the promise: goal, where, how long. */
export function pactFacts(
  profile: Pick<Profile, 'goal' | 'location' | 'minutes_per_session'>,
): { value: string; label: string }[] {
  return [
    { value: GOALS[profile.goal], label: 'Goal' },
    { value: profile.location === 'gym' ? 'Gym' : 'Home', label: 'Where' },
    {
      value: profile.minutes_per_session === null ? 'No limit' : `${profile.minutes_per_session} min`,
      label: 'Each time',
    },
  ];
}

/** "THU · 26 NOV": today, on the phone's calendar. */
export function pactDate(now: Date): string {
  return `${DAYS[now.getDay()]} · ${now.getDate()} ${MONTHS[now.getMonth()]}`;
}

/** A signature counts once it's more than a dot: enough points drawn in total. */
export const MIN_POINTS = 8;

export type Point = { x: number; y: number };

/** One drawn stroke as an SVG path ("M x y L x y …"). */
export function strokePath(points: Point[]): string {
  const [first, ...rest] = points;
  if (first === undefined) return '';
  const round = (n: number) => Math.round(n * 10) / 10;
  if (rest.length === 0) return `M${round(first.x)} ${round(first.y)} l0.1 0`;
  return `M${round(first.x)} ${round(first.y)} ${rest.map((p) => `L${round(p.x)} ${round(p.y)}`).join(' ')}`;
}

export function isSigned(strokes: Point[][]): boolean {
  return strokes.reduce((total, stroke) => total + stroke.length, 0) >= MIN_POINTS;
}

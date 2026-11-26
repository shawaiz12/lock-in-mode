/**
 * Words and small sums for the weekly ring, the streak, new bests and the reminder
 * (ADR 0034). Pure, so they're tested without screens.
 *
 * Tone: real progress first, never shame. A missed week says what happens next ("a new
 * streak starts this week"), not what was lost.
 */
import type { components } from '@/api/schema';

type Week = components['schemas']['WeekRead'];
type NewBest = components['schemas']['NewBest'];
type Reminder = components['schemas']['Reminder'];

const DAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** The ring: one dot per planned workout, filled for each done ("●●○"). Done beyond the
 * plan adds filled dots. */
export function ringDots(done: number, planned: number | null): boolean[] {
  const total = Math.max(planned ?? 0, done, 1);
  return Array.from({ length: total }, (_, i) => i < done);
}

export function ringLabel(week: Pick<Week, 'done' | 'planned'>): string {
  return week.planned ? `${week.done} of ${week.planned} workouts` : `${week.done} workouts`;
}

export function streakLine(week: Pick<Week, 'streak' | 'kept' | 'done' | 'keep_at'>): string {
  const left = Math.max(week.keep_at - week.done, 0);
  if (week.streak === 0) {
    return left === 1 ? '1 more workout this week starts a streak.' : `${week.keep_at} workouts this week start a streak.`;
  }
  const weeks = week.streak === 1 ? '1-week streak' : `${week.streak}-week streak`;
  if (week.kept) return `${weeks}. This week counts.`;
  return left === 1 ? `${weeks}. 1 more workout keeps it going.` : `${weeks}. ${left} more workouts keep it going.`;
}

export function freezeLine(week: Pick<Week, 'freezes' | 'last_week'>): string | null {
  if (week.last_week === 'frozen') return 'A freeze saved last week. Your streak is safe.';
  if (week.freezes === 0) return null;
  return week.freezes === 1 ? '1 freeze ready: it saves a week you miss.' : '2 freezes ready: each saves a week you miss.';
}

export function lastWeekLine(week: Pick<Week, 'last_week' | 'streak'>): string | null {
  return week.last_week === 'missed' && week.streak === 0 ? 'Last week was quiet. A new streak starts this week.' : null;
}

/** "New best: 14 push-ups", "New best: Goblet squat 16 kg", "New best: Plank 50 s". */
export function newBestLine(best: NewBest): string {
  const value = Number.isInteger(best.value) ? String(best.value) : best.value.toFixed(1);
  if (best.kind === 'weight') return `New best: ${best.exercise.name} ${value} kg`;
  if (best.kind === 'seconds') return `New best: ${best.exercise.name} ${value} s`;
  return `New best: ${value} reps of ${best.exercise.name}`;
}

/** The week just kept by this workout: worth a line on the finish screen. */
export function keptNowLine(week: Pick<Week, 'done' | 'keep_at' | 'streak' | 'planned'> | null | undefined): string | null {
  if (!week || week.done !== week.keep_at) return null;
  return week.streak > 1 ? `This week counts: ${week.streak}-week streak.` : 'This week counts: your streak has started.';
}

// --- the reminder --------------------------------------------------------------------------

export type ClockTime = { hour: number; minute: number };

/** The time they just trained at, to the nearest half hour: the Paved Path default. */
export function suggestTime(now: Date): ClockTime {
  const minutes = Math.round((now.getHours() * 60 + now.getMinutes()) / 30) * 30;
  const wrapped = minutes % (24 * 60);
  return { hour: Math.floor(wrapped / 60), minute: wrapped % 60 };
}

export function stepTime(time: ClockTime, direction: -1 | 1): ClockTime {
  const minutes = (time.hour * 60 + time.minute + direction * 30 + 24 * 60) % (24 * 60);
  return { hour: Math.floor(minutes / 60), minute: minutes % 60 };
}

export function formatTime(time: ClockTime): string {
  return `${String(time.hour).padStart(2, '0')}:${String(time.minute).padStart(2, '0')}`;
}

/** "18:30:00" (the API's time) → 18:30. */
export function parseTime(at: string): ClockTime {
  const [hour = '0', minute = '0'] = at.split(':');
  return { hour: Number(hour), minute: Number(minute) };
}

export function dayName(day: number): string {
  return DAY_SHORT[day] ?? '?';
}

/** "Mon, Wed, Fri at 18:30". */
export function reminderSummary(reminder: Reminder): string {
  const days = reminder.days.length === 7 ? 'Every day' : reminder.days.map(dayName).join(', ');
  return `${days} at ${formatTime(parseTime(reminder.at))}`;
}

/** 0 = Monday (ours) → expo-notifications' weekday, where 1 = Sunday … 7 = Saturday. */
export function toPhoneWeekday(day: number): number {
  return ((day + 1) % 7) + 1;
}

/** What the character says on Home (ADR 0036): short, about what's next, never a loss. */
export function bubbleLine(week: Pick<Week, 'done' | 'keep_at' | 'kept'>): string {
  if (week.kept) return 'This week counts!';
  if (week.done === 0) return 'Ready when you are.';
  const left = Math.max(week.keep_at - week.done, 0);
  return left === 1 ? '1 more this week?' : `${left} more this week?`;
}

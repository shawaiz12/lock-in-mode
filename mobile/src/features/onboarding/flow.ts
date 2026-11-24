/**
 * The onboarding quiz (docs/onboarding.md): which screens, in what order, what each
 * answer becomes in the profile. Plain functions, no React: easy to test, easy to read.
 * .NET: a small domain model + a mapper to the request DTO.
 *
 * Rules from the playbook: one question per screen, one tap to answer (single choices
 * move on by themselves), every question changes the plan or how we talk to the user,
 * echo big answers back, about 10 taps.
 */
import type { components } from '@/api/schema';

type Schemas = components['schemas'];
export type Goal = Schemas['Goal'];
export type Location = Schemas['Location'];
export type HomeEquipment = Exclude<Schemas['Equipment'], 'gym'>;
export type BodyLimit = Schemas['BodyLimit'];
export type Obstacle = Schemas['Obstacle'];
export type SessionMinutes = Schemas['SessionMinutes'];
type ProfileWrite = Schemas['ProfileWrite'];

/** Training history, asked instead of "how fit are you?" (self-rating is unreliable). */
export type History = 'never_or_on_and_off' | 'six_months_to_two_years' | 'two_years_plus';

export type Answers = {
  name: string;
  goal?: Goal;
  history?: History;
  location?: Location;
  equipment: HomeEquipment[];
  /** "Quiet, small-space workouts" (stored as women_home_track until it's renamed). */
  quiet: boolean;
  days?: number;
  /** undefined: not answered yet. null: "No limit". */
  minutes?: SessionMinutes | null;
  limits: BodyLimit[];
  obstacles: Obstacle[];
};

export const EMPTY_ANSWERS: Answers = {
  name: '',
  equipment: [],
  quiet: false,
  limits: [],
  obstacles: [],
};

export type StepId =
  | 'welcome'
  | 'goal'
  | 'echo'
  | 'history'
  | 'where'
  | 'equipment'
  | 'days'
  | 'time'
  | 'limits'
  | 'obstacles';

/** The screens for these answers. Equipment is asked at home only: gym users have it all. */
export function stepsFor(answers: Answers): StepId[] {
  const steps: StepId[] = ['welcome', 'goal', 'echo', 'history', 'where'];
  if (answers.location === 'home') steps.push('equipment');
  steps.push('days', 'time', 'limits', 'obstacles');
  return steps;
}

/** Can the person move on from this screen? */
export function isAnswered(step: StepId, answers: Answers): boolean {
  switch (step) {
    case 'goal':
      return answers.goal !== undefined;
    case 'history':
      return answers.history !== undefined;
    case 'where':
      return answers.location !== undefined;
    case 'days':
      return answers.days !== undefined;
    case 'time':
      return answers.minutes !== undefined;
    // Name (optional), echo, equipment (none is a full plan), limits (none is an
    // answer), obstacles (skippable): always fine.
    default:
      return true;
  }
}

export const GOALS: { value: Goal; label: string; echo: string }[] = [
  {
    value: 'build_muscle',
    label: 'Build muscle',
    echo: 'Build muscle: every part of each muscle gets trained, and your numbers go up as you earn it.',
  },
  {
    value: 'strength',
    label: 'Build strength',
    echo: 'Build strength: your main lifts get longer rests so every rep is strong, and they step up as you get stronger.',
  },
  {
    value: 'lose_fat',
    label: 'Lose fat / get fit',
    echo: 'Fat loss comes mostly from eating less than you burn. Training shapes what you keep.',
  },
  {
    value: 'stamina',
    label: 'Improve stamina',
    echo: 'Improve stamina: about half your days are cardio, and strength days are circuits that keep your heart rate up.',
  },
  {
    value: 'stay_active',
    label: 'Stay active',
    echo: 'Stay active: full body on 2 to 3 days. Easy walks on the other days still count.',
  },
];

export const HISTORY: { value: History; label: string }[] = [
  { value: 'never_or_on_and_off', label: 'Never, on and off, or under 6 months' },
  { value: 'six_months_to_two_years', label: '6 months to 2 years' },
  { value: 'two_years_plus', label: '2+ years' },
];

export const LOCATIONS: { value: Location; label: string }[] = [
  { value: 'home', label: 'Home' },
  { value: 'gym', label: 'Gym' },
];

export const EQUIPMENT: { value: HomeEquipment; label: string }[] = [
  { value: 'dumbbells', label: 'Dumbbells' },
  { value: 'resistance_bands', label: 'Bands' },
  { value: 'pull_up_bar', label: 'Pull-up bar' },
];

export const DAYS = [2, 3, 4, 5, 6] as const;

export const MINUTES: { value: SessionMinutes | null; label: string }[] = [
  { value: 10, label: '10 min' },
  { value: 20, label: '20 min' },
  { value: 30, label: '30 min' },
  { value: 45, label: '45 min' },
  { value: 60, label: '60 min' },
  { value: 75, label: '75 min' },
  { value: 90, label: '90 min' },
  { value: null, label: 'No limit' },
];

export const LIMITS: { value: BodyLimit; label: string }[] = [
  { value: 'knees', label: 'Knees' },
  { value: 'back', label: 'Back' },
  { value: 'shoulders', label: 'Shoulders' },
];

export const OBSTACLES: { value: Obstacle; label: string }[] = [
  { value: 'no_time', label: 'No time' },
  { value: 'dont_know_what_to_do', label: "Don't know what to do" },
  { value: 'lose_motivation', label: 'Lose motivation' },
  { value: 'get_bored', label: 'Get bored' },
];

const LEVEL_FOR_HISTORY: Record<History, ProfileWrite['level']> = {
  never_or_on_and_off: 'beginner',
  six_months_to_two_years: 'some_experience',
  two_years_plus: 'experienced',
};

export function echoFor(goal: Goal | undefined): string {
  return GOALS.find((g) => g.value === goal)?.echo ?? '';
}

/** Add or remove one value of a multi-choice answer. */
export function toggle<T>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

/** Changing where you train resets the home-only answers, so a gym user never sends
 * home equipment (the API would refuse it). */
export function chooseLocation(answers: Answers, location: Location): Answers {
  return location === 'gym'
    ? { ...answers, location, equipment: [], quiet: false }
    : { ...answers, location };
}

export class IncompleteAnswersError extends Error {}

/** The PUT /me/profile body. Throws if a required answer is missing (a bug: the
 * screens don't let you get to the end without them). */
export function toProfileWrite(answers: Answers): ProfileWrite {
  const { goal, history, location, days, minutes } = answers;
  if (!goal || !history || !location || days === undefined || minutes === undefined) {
    throw new IncompleteAnswersError('Onboarding answers are incomplete.');
  }
  const home = location === 'home';
  return {
    goal,
    level: LEVEL_FOR_HISTORY[history],
    location,
    equipment: home ? answers.equipment : [],
    women_home_track: home && answers.quiet,
    days_per_week: days,
    minutes_per_session: minutes,
    limits: answers.limits,
    obstacles: answers.obstacles,
  };
}

/** The optional name, tidied; null if none was given. */
export function displayName(answers: Answers): string | null {
  const name = answers.name.trim().slice(0, 50);
  return name.length > 0 ? name : null;
}

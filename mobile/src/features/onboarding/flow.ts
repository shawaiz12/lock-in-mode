/**
 * The onboarding quiz (docs/onboarding.md, ADR 0036): which screens, in what order, what
 * each answer becomes in the profile. Plain functions, no React: easy to test, easy to read.
 * .NET: a small domain model + a mapper to the request DTO.
 *
 * Rules from the playbook: one question per screen, one tap to answer (single choices
 * move on by themselves), every question changes the plan or it goes, say WHY each answer
 * is needed, show progress. ADR 0036 cut it from 12 screens to 8: no welcome or name
 * screen (the pact's signature is theirs; the name is in Settings), the goal's echo shows
 * on the next screen instead of its own, home kit is asked on the "where" screen, the
 * unused "what's made it hard" question is gone, and the safety check is one list.
 */
import type { components } from '@/api/schema';

type Schemas = components['schemas'];
export type Goal = Schemas['Goal'];
export type Location = Schemas['Location'];
export type HomeEquipment = Exclude<Schemas['Equipment'], 'gym'>;
export type BodyLimit = Schemas['BodyLimit'];
export type SessionMinutes = Schemas['SessionMinutes'];
type ProfileWrite = Schemas['ProfileWrite'];

/** Training history, asked instead of "how fit are you?" (self-rating is unreliable). */
export type History = 'never_or_on_and_off' | 'six_months_to_two_years' | 'two_years_plus';

export type Answers = {
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
};

export const EMPTY_ANSWERS: Answers = {
  equipment: [],
  quiet: false,
  limits: [],
};

export type StepId = 'goal' | 'history' | 'where' | 'days' | 'time' | 'limits';

/** The questions, in order. Home kit is part of "where" (asked only after "Home"). */
export const STEPS: readonly StepId[] = ['goal', 'history', 'where', 'days', 'time', 'limits'];

/** The whole first run, for the progress bar: these questions, the safety list, the pact. */
export const FLOW_LENGTH = STEPS.length + 2;
export const SAFETY_STEP = STEPS.length + 1;
export const PACT_STEP = STEPS.length + 2;

/** Each question's title and the one line that says why it's asked. */
export const QUESTIONS: Record<StepId, { title: string; why: string }> = {
  goal: {
    title: 'What’s your goal?',
    why: 'It shapes every workout: which exercises, how many reps, how long you rest.',
  },
  history: {
    title: 'How long have you trained steadily?',
    why: 'How long you’ve trained says more than how fit you feel. Workout 1 then finds your real numbers.',
  },
  where: {
    title: 'Where will you train?',
    why: 'So every exercise in your plan is one you can really do there.',
  },
  days: {
    title: 'How many days a week can you train?',
    why: 'Your plan is built around this. Fewer days you’ll really keep beats more days you’ll skip.',
  },
  time: {
    title: 'How long per workout?',
    why: 'Every workout fits in this. 10 minutes counts.',
  },
  limits: {
    title: 'Anything to train around?',
    why: 'We train around a sore area. We don’t treat it.',
  },
};

/** Single answers move on by themselves; these screens need the "Lock In" button. */
export function needsButton(step: StepId, answers: Answers): boolean {
  if (step === 'where') return answers.location === 'home';
  return step === 'limits' && answers.limits.length > 0;
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
    // Limits: none is an answer too.
    default:
      return true;
  }
}

export const GOALS: { value: Goal; label: string; hint: string; echo: string }[] = [
  {
    value: 'build_muscle',
    label: 'Build muscle',
    hint: 'Bigger, fuller muscles',
    echo: 'Build muscle: every part of each muscle gets trained, and your numbers go up as you earn it.',
  },
  {
    value: 'strength',
    label: 'Build strength',
    hint: 'Lift heavier',
    echo: 'Build strength: your main lifts get longer rests so every rep is strong, and they step up as you get stronger.',
  },
  {
    value: 'lose_fat',
    label: 'Lose fat / get fit',
    hint: 'Leaner and fitter',
    echo: 'Fat loss comes mostly from eating less than you burn. Training shapes what you keep.',
  },
  {
    value: 'stamina',
    label: 'Improve stamina',
    hint: 'Last longer, breathe easier',
    echo: 'Improve stamina: about half your days are cardio, and strength days are circuits that keep your heart rate up.',
  },
  {
    value: 'stay_active',
    label: 'Stay active',
    hint: 'Move well, feel good',
    echo: 'Stay active: full body on 2 to 3 days. Easy walks on the other days still count.',
  },
];

export const HISTORY: { value: History; label: string; hint?: string }[] = [
  {
    value: 'never_or_on_and_off',
    label: 'Never, on and off, or under 6 months',
    hint: 'Workout 1 finds your starting point',
  },
  { value: 'six_months_to_two_years', label: '6 months to 2 years' },
  { value: 'two_years_plus', label: '2+ years' },
];

export const LOCATIONS: { value: Location; label: string; hint: string }[] = [
  { value: 'gym', label: 'Gym', hint: 'Machines, barbells and dumbbells' },
  { value: 'home', label: 'Home', hint: 'Your body, plus anything you have' },
];

export const EQUIPMENT: { value: HomeEquipment; label: string }[] = [
  { value: 'dumbbells', label: 'Dumbbells' },
  { value: 'resistance_bands', label: 'Bands' },
  { value: 'pull_up_bar', label: 'Pull-up bar' },
];

export const DAYS = [2, 3, 4, 5, 6] as const;

/** One line per number of days. Never a promised split: the routine depends on the goal
 * and level too (training/routine.py). */
export const DAY_HINTS: Record<(typeof DAYS)[number], string> = {
  2: 'Busy weeks still count',
  3: 'Most people start here',
  4: 'More time for each muscle',
  5: 'Training is part of your routine',
  6: 'As much as you can give',
};

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
    // Not asked any more (ADR 0036): nothing used it yet.
    obstacles: [],
  };
}

/** A name typed in Settings, tidied; null if it's empty. */
export function cleanName(text: string): string | null {
  const name = text.trim().slice(0, 50);
  return name.length > 0 ? name : null;
}

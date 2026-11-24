/** The four safety questions (ADR 0012) and when they're all answered. */
import type { SafetyScreen } from '@/api/endpoints';

export const QUESTIONS: { key: keyof SafetyScreen; text: string }[] = [
  { key: 'heart_condition', text: 'Has a doctor ever said you have a heart condition?' },
  { key: 'chest_pain_when_active', text: 'Do you get chest pain when you are active?' },
  { key: 'pregnant', text: 'Are you pregnant?' },
  { key: 'recent_surgery_or_injury', text: 'Have you had surgery or an injury recently?' },
];

export type SafetyAnswers = Partial<Record<keyof SafetyScreen, boolean>>;

/** All four answered: the request body. Otherwise null (the button stays off). */
export function completeAnswers(answers: SafetyAnswers): SafetyScreen | null {
  const [heart, chest, pregnant, surgery] = QUESTIONS.map((q) => answers[q.key]);
  if (heart === undefined || chest === undefined || pregnant === undefined || surgery === undefined) {
    return null;
  }
  return {
    heart_condition: heart,
    chest_pain_when_active: chest,
    pregnant,
    recent_surgery_or_injury: surgery,
  };
}

export function anyYes(answers: SafetyAnswers): boolean {
  return Object.values(answers).some((value) => value === true);
}

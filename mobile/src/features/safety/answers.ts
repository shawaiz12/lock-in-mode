/**
 * The four safety questions (ADR 0012), asked as ONE list since ADR 0036: tick any that
 * apply, or "None of these" (one tap for most people). The server still gets all four
 * yes/no answers, and keeps only the result.
 */
import type { SafetyScreen } from '@/api/endpoints';

export type SafetyKey = keyof SafetyScreen;

export const QUESTIONS: { key: SafetyKey; item: string }[] = [
  { key: 'heart_condition', item: 'A doctor has said I have a heart condition' },
  { key: 'chest_pain_when_active', item: 'I get chest pain when I’m active' },
  { key: 'pregnant', item: 'I’m pregnant' },
  { key: 'recent_surgery_or_injury', item: 'I’ve had surgery or an injury recently' },
];

/** The request body: the ticked ones are "yes", every other one "no". */
export function screenFrom(ticked: readonly SafetyKey[]): SafetyScreen {
  const yes = (key: SafetyKey) => ticked.includes(key);
  return {
    heart_condition: yes('heart_condition'),
    chest_pain_when_active: yes('chest_pain_when_active'),
    pregnant: yes('pregnant'),
    recent_surgery_or_injury: yes('recent_surgery_or_injury'),
  };
}

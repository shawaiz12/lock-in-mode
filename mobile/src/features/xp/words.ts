/**
 * Words for XP and the Lock In level (ADR 0035). Pure, tested without screens.
 * XP is the second line: real progress (new bests, "This week counts") comes first.
 */
import type { components } from '@/api/schema';

type XpLevel = components['schemas']['XpLevel'];
type XpItem = components['schemas']['XpItem'];

const LABELS: Record<XpItem['source'], string> = {
  workout: 'Workout',
  week: 'Week kept',
  best: 'New bests',
  comeback: 'Welcome back',
  bonus: 'Locked-in bonus',
};

/** 1000 → "1,000" (the same on every phone, whatever its language). */
export function thousands(n: number): string {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

export function xpItemLine(item: XpItem): string {
  return `${LABELS[item.source]} +${thousands(item.amount)}`;
}

/** "Lock In level 7 · 320 / 1,000 XP" */
export function levelLine(level: XpLevel): string {
  return `Lock In level ${level.level} · ${thousands(level.xp_into)} / ${thousands(level.xp_needed)} XP`;
}

/** 0..1 through the current level. */
export function levelShare(level: XpLevel): number {
  return level.xp_needed > 0 ? Math.min(1, level.xp_into / level.xp_needed) : 0;
}

export const CAPPED_LINE = 'Rest counts too: you’ve done your week.';

/** The HUD's two parts of `levelLine`: "Lock In level 7" and "320 / 1,000 XP". */
export function levelParts(level: XpLevel): [string, string] {
  return [`Lock In level ${level.level}`, `${thousands(level.xp_into)} / ${thousands(level.xp_needed)} XP`];
}

/** "1 new best" / "9 new bests", for the tile's small line. */
export function bestsWord(total: number): string {
  return total === 1 ? 'new best' : 'new bests';
}

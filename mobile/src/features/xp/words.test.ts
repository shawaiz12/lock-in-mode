import { levelLine, levelShare, thousands, xpItemLine } from './words';

it('thousands, the same on every phone', () => {
  expect([0, 999, 1000, 14500, 1234567].map(thousands)).toEqual(['0', '999', '1,000', '14,500', '1,234,567']);
});

it('the level line and the bar', () => {
  const level = { total: 1320, level: 7, xp_into: 320, xp_needed: 1000 };
  expect(levelLine(level)).toBe('Lock In level 7 · 320 / 1,000 XP');
  expect(levelShare(level)).toBeCloseTo(0.32);
  expect(levelShare({ ...level, xp_needed: 0 })).toBe(0);
});

it('each XP item says what it was for', () => {
  expect(xpItemLine({ source: 'workout', amount: 100 })).toBe('Workout +100');
  expect(xpItemLine({ source: 'week', amount: 150 })).toBe('Week kept +150');
  expect(xpItemLine({ source: 'best', amount: 50 })).toBe('New bests +50');
  expect(xpItemLine({ source: 'comeback', amount: 100 })).toBe('Welcome back +100');
  expect(xpItemLine({ source: 'bonus', amount: 1000 })).toBe('Locked-in bonus +1,000');
});

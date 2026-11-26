import { isSigned, MIN_POINTS, pactDate, pactFacts, promiseLines, strokePath } from './words';

describe('the pact’s words', () => {
  it('promises their own days, the 2-workout week, and a comeback', () => {
    expect(promiseLines({ days_per_week: 4 })).toEqual([
      'I train 4 days a week. Any week with 2 workouts counts.',
      'If I miss a week, I come back.',
    ]);
  });

  it('shows the goal, where and how long', () => {
    expect(pactFacts({ goal: 'lose_fat', location: 'home', minutes_per_session: 20 })).toEqual([
      { value: 'Get fit', label: 'Goal' },
      { value: 'Home', label: 'Where' },
      { value: '20 min', label: 'Each time' },
    ]);
    expect(pactFacts({ goal: 'strength', location: 'gym', minutes_per_session: null })[2]?.value).toBe('No limit');
  });

  it('dates it the way the mockup does', () => {
    expect(pactDate(new Date(2026, 10, 26, 12))).toBe('THU · 26 NOV');
  });
});

describe('the signature', () => {
  it('turns a stroke into a path', () => {
    expect(strokePath([])).toBe('');
    expect(strokePath([{ x: 1.04, y: 2 }])).toBe('M1 2 l0.1 0'); // a dot still shows
    expect(strokePath([{ x: 0, y: 0 }, { x: 10.26, y: 5 }])).toBe('M0 0 L10.3 5');
  });

  it('counts as signed once it’s more than a dot', () => {
    const points = (n: number) => Array.from({ length: n }, (_, i) => ({ x: i, y: i }));
    expect(isSigned([])).toBe(false);
    expect(isSigned([points(MIN_POINTS - 1)])).toBe(false);
    expect(isSigned([points(3), points(MIN_POINTS - 3)])).toBe(true); // across strokes
  });
});

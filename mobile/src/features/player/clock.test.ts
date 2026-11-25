import {
  addSeconds,
  countdown,
  countInBeeps,
  formatClock,
  isOver,
  isRunning,
  pause,
  reading,
  resume,
  secondsDone,
  stopwatch,
} from './clock';

describe('countdown', () => {
  it('counts down from when it started, never below zero', () => {
    const c = countdown(90, 1_000);

    expect(reading(c, 1_000)).toBe(90_000);
    expect(reading(c, 31_000)).toBe(60_000);
    expect(reading(c, 200_000)).toBe(0);
    expect(isOver(c, 90_999)).toBe(false);
    expect(isOver(c, 91_000)).toBe(true);
  });

  it('is right however late it is read (a locked phone, a slow frame)', () => {
    const c = countdown(30, 0);

    expect(reading(c, 29_400)).toBe(600);
  });

  it('pauses and resumes where it was', () => {
    let c = countdown(60, 0);
    c = pause(c, 20_000);

    expect(isRunning(c)).toBe(false);
    expect(reading(c, 500_000)).toBe(40_000);

    c = resume(c, 100_000);
    expect(reading(c, 110_000)).toBe(30_000);
  });

  it('+15 s adds to what is left, running or paused', () => {
    expect(reading(addSeconds(countdown(60, 0), 15, 50_000), 50_000)).toBe(25_000);
    expect(reading(addSeconds(pause(countdown(60, 0), 50_000), 15, 70_000), 90_000)).toBe(25_000);
  });

  it('stopped early: the whole seconds really done', () => {
    expect(secondsDone(countdown(30, 0), 21_400)).toBe(21);
    expect(secondsDone(countdown(30, 0), 99_000)).toBe(30);
  });
});

describe('stopwatch', () => {
  it('counts up, pauses, and says how long', () => {
    let s = stopwatch(0);
    expect(reading(s, 42_000)).toBe(42_000);
    s = pause(s, 42_000);
    s = resume(s, 60_000);
    expect(secondsDone(s, 63_000)).toBe(45);
    expect(isOver(s, 1e9)).toBe(false);
  });
});

describe('formatClock', () => {
  it('rounds a countdown up and a stopwatch down', () => {
    expect(formatClock(90_000, true)).toBe('1:30');
    expect(formatClock(400, true)).toBe('0:01');
    expect(formatClock(0, true)).toBe('0:00');
    expect(formatClock(59_900, false)).toBe('0:59');
    expect(formatClock(605_000, false)).toBe('10:05');
  });
});

describe('countInBeeps', () => {
  it('beeps at 3, 2 and 1 seconds left, once each', () => {
    expect(countInBeeps(3_200, 2_950)).toEqual([3]);
    expect(countInBeeps(2_950, 2_700)).toEqual([]);
    expect(countInBeeps(2_100, 1_900)).toEqual([2]);
    expect(countInBeeps(Infinity, 500)).toEqual([3, 2, 1]);
    expect(countInBeeps(10_000, 9_750)).toEqual([]);
  });
});

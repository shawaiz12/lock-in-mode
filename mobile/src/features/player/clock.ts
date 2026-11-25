/**
 * Countdowns (rest, timed moves) and the stopwatch (strength-test holds), as plain data.
 * Pure (clock.test.ts).
 *
 * A clock stores WHEN it ends, not how many seconds are left: the phone can lock, the app
 * can go to the background, a frame can be late, and the time left is still right the
 * moment the screen looks again. .NET: like keeping a DateTime deadline instead of
 * decrementing a counter in Update().
 */
export type Clock =
  | { kind: 'countdown'; totalMs: number; endsAt: number | null; pausedLeftMs: number }
  | { kind: 'stopwatch'; startedAt: number | null; pausedMs: number };

export function countdown(seconds: number, now: number): Clock {
  const totalMs = seconds * 1000;
  return { kind: 'countdown', totalMs, endsAt: now + totalMs, pausedLeftMs: totalMs };
}

export function stopwatch(now: number): Clock {
  return { kind: 'stopwatch', startedAt: now, pausedMs: 0 };
}

export function isRunning(clock: Clock): boolean {
  return clock.kind === 'countdown' ? clock.endsAt !== null : clock.startedAt !== null;
}

/** Countdown: ms left (never below 0). Stopwatch: ms so far. */
export function reading(clock: Clock, now: number): number {
  if (clock.kind === 'countdown') {
    return clock.endsAt === null ? clock.pausedLeftMs : Math.max(0, clock.endsAt - now);
  }
  return clock.pausedMs + (clock.startedAt === null ? 0 : now - clock.startedAt);
}

export function isOver(clock: Clock, now: number): boolean {
  return clock.kind === 'countdown' && reading(clock, now) === 0;
}

export function pause(clock: Clock, now: number): Clock {
  if (!isRunning(clock)) return clock;
  return clock.kind === 'countdown'
    ? { ...clock, endsAt: null, pausedLeftMs: reading(clock, now) }
    : { ...clock, startedAt: null, pausedMs: reading(clock, now) };
}

export function resume(clock: Clock, now: number): Clock {
  if (isRunning(clock)) return clock;
  return clock.kind === 'countdown'
    ? { ...clock, endsAt: now + clock.pausedLeftMs }
    : { ...clock, startedAt: now };
}

/** "+15 s" on a rest. */
export function addSeconds(clock: Clock, seconds: number, now: number): Clock {
  if (clock.kind !== 'countdown') return clock;
  const left = reading(clock, now) + seconds * 1000;
  return {
    ...clock,
    totalMs: clock.totalMs + seconds * 1000,
    endsAt: clock.endsAt === null ? null : now + left,
    pausedLeftMs: left,
  };
}

/** Whole seconds of work done: a countdown stopped early, or a stopwatch. */
export function secondsDone(clock: Clock, now: number): number {
  const ms = clock.kind === 'countdown' ? clock.totalMs - reading(clock, now) : reading(clock, now);
  return Math.round(ms / 1000);
}

/** What the big clock shows: "1:30", "0:09". A countdown rounds up (it reads 0:01 until
 * the very end), a stopwatch rounds down. */
export function formatClock(ms: number, roundUp: boolean): string {
  const total = roundUp ? Math.ceil(ms / 1000) : Math.floor(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

/**
 * Which short beeps are due between two readings of a countdown: 3, 2 and 1 seconds
 * before the end (the "get ready"), so the person knows without looking.
 */
export function countInBeeps(beforeMs: number, afterMs: number): number[] {
  const due: number[] = [];
  for (const mark of [3, 2, 1]) {
    if (beforeMs > mark * 1000 && afterMs <= mark * 1000) due.push(mark);
  }
  return due;
}

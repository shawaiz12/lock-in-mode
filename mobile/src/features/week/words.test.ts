import {
  bubbleLine,
  formatTime,
  freezeLine,
  keptNowLine,
  lastWeekLine,
  newBestLine,
  parseTime,
  reminderSummary,
  ringDots,
  ringLabel,
  stepTime,
  streakLine,
  suggestTime,
  toPhoneWeekday,
} from './words';

const week = { done: 1, planned: 3, keep_at: 2, kept: false, streak: 0, freezes: 0, last_week: null } as const;
const ex = { id: 'e', slug: 'push-up', name: 'Push-up', difficulty: 2 };

it('the ring: a dot per planned workout, done ones filled, extra workouts add dots', () => {
  expect(ringDots(2, 3)).toEqual([true, true, false]);
  expect(ringDots(4, 3)).toEqual([true, true, true, true]);
  expect(ringDots(0, null)).toEqual([false]);
  expect(ringLabel({ done: 2, planned: 3 })).toBe('2 of 3 workouts');
});

it('the streak line says what keeps it going, never what was lost', () => {
  expect(streakLine(week)).toBe('1 more workout this week starts a streak.');
  expect(streakLine({ ...week, done: 0 })).toBe('2 workouts this week start a streak.');
  expect(streakLine({ ...week, streak: 3 })).toBe('3-week streak. 1 more workout keeps it going.');
  expect(streakLine({ ...week, streak: 1, done: 0 })).toBe('1-week streak. 2 more workouts keep it going.');
  expect(streakLine({ ...week, streak: 4, kept: true, done: 2 })).toBe('4-week streak. This week counts.');
});

it('freezes and last week', () => {
  expect(freezeLine({ freezes: 0, last_week: 'kept' })).toBeNull();
  expect(freezeLine({ freezes: 2, last_week: 'kept' })).toBe('2 freezes ready: each saves a week you miss.');
  expect(freezeLine({ freezes: 0, last_week: 'frozen' })).toBe('A freeze saved last week. Your streak is safe.');
  expect(lastWeekLine({ last_week: 'missed', streak: 0 })).toBe('Last week was quiet. A new streak starts this week.');
  expect(lastWeekLine({ last_week: 'kept', streak: 2 })).toBeNull();
});

it('new bests read as real progress', () => {
  expect(newBestLine({ exercise: ex, kind: 'reps', value: 14, previous: 12 })).toBe('New best: 14 reps of Push-up');
  expect(newBestLine({ exercise: { ...ex, name: 'Goblet squat' }, kind: 'weight', value: 16.25, previous: 14 })).toBe(
    'New best: Goblet squat 16.3 kg',
  );
  expect(newBestLine({ exercise: { ...ex, name: 'Plank' }, kind: 'seconds', value: 50, previous: 45 })).toBe(
    'New best: Plank 50 s',
  );
});

it('the finish screen says so only when this workout kept the week', () => {
  expect(keptNowLine({ done: 2, keep_at: 2, streak: 1, planned: 3 })).toBe('This week counts: your streak has started.');
  expect(keptNowLine({ done: 2, keep_at: 2, streak: 5, planned: 3 })).toBe('This week counts: 5-week streak.');
  expect(keptNowLine({ done: 3, keep_at: 2, streak: 5, planned: 3 })).toBeNull();
  expect(keptNowLine(null)).toBeNull();
});

it('the reminder time: the time just trained, to the half hour, in half-hour steps', () => {
  expect(suggestTime(new Date(2026, 10, 25, 18, 14))).toEqual({ hour: 18, minute: 0 });
  expect(suggestTime(new Date(2026, 10, 25, 18, 16))).toEqual({ hour: 18, minute: 30 });
  expect(suggestTime(new Date(2026, 10, 25, 23, 50))).toEqual({ hour: 0, minute: 0 });
  expect(stepTime({ hour: 23, minute: 30 }, 1)).toEqual({ hour: 0, minute: 0 });
  expect(stepTime({ hour: 0, minute: 0 }, -1)).toEqual({ hour: 23, minute: 30 });
  expect(formatTime(parseTime('07:30:00'))).toBe('07:30');
});

it('reminder days, and the phone’s weekday numbers (1 = Sunday)', () => {
  expect(reminderSummary({ at: '18:30:00', days: [0, 2, 4] })).toBe('Mon, Wed, Fri at 18:30');
  expect(reminderSummary({ at: '07:00:00', days: [0, 1, 2, 3, 4, 5, 6] })).toBe('Every day at 07:00');
  expect([0, 1, 2, 3, 4, 5, 6].map(toPhoneWeekday)).toEqual([2, 3, 4, 5, 6, 7, 1]);
});

it('the character says what’s next, never what’s lost (ADR 0036)', () => {
  expect(bubbleLine({ done: 0, keep_at: 2, kept: false })).toBe('Ready when you are.');
  expect(bubbleLine({ done: 1, keep_at: 2, kept: false })).toBe('1 more this week?');
  expect(bubbleLine({ done: 2, keep_at: 2, kept: true })).toBe('This week counts!');
  expect(bubbleLine({ done: 0, keep_at: 3, kept: false })).toBe('Ready when you are.');
  expect(bubbleLine({ done: 1, keep_at: 3, kept: false })).toBe('2 more this week?');
});

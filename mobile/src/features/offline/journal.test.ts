import {
  begin,
  finishHere,
  finished,
  hasProgress,
  type Journal,
  loggedSets,
  nextStep,
  parseJournal,
  record,
  sent,
  started,
  waiting,
} from './journal';

const T0 = '2026-11-25T10:00:00.000Z';
const T1 = '2026-11-25T10:05:00.000Z';
const T2 = '2026-11-25T10:09:00.000Z';
const EIGHT = { reps: 8, weight_kg: 40, seconds: null };
const TEN = { reps: 10, weight_kg: 40, seconds: null };

function session(sets: { planned_exercise_id: string; set_number: number; reps: number }[] = []) {
  return {
    id: 's1',
    workout_id: 'w1',
    started_at: T0,
    finished_at: null,
    feedback: null,
    sets: sets.map((s) => ({ ...s, weight_kg: null, seconds: null })),
  };
}

const fresh = () => begin('w1', 4, T0);

it('starts with nothing done and the start waiting to be sent', () => {
  const j = fresh();
  expect(loggedSets(j)).toEqual([]);
  expect(hasProgress(j)).toBe(false);
  expect(waiting(j)).toBe(1);
  expect(nextStep(j)).toEqual({ kind: 'start' });
});

it('sends the start, then each set change, then the finish', () => {
  let j: Journal = record(fresh(), 'a', 1, EIGHT, T1);
  j = finishHere(j, 'just_right', T2);
  expect(nextStep(j)?.kind).toBe('start');

  j = started(j, session());
  const step = nextStep(j);
  expect(step).toMatchObject({ kind: 'set', key: 'a/1', sessionId: 's1' });

  j = sent(j, 'a/1', 1);
  expect(nextStep(j)).toEqual({ kind: 'finish', sessionId: 's1', feedback: 'just_right', at: T2 });
  j = finished(j, null);
  expect(nextStep(j)).toBeNull();
  expect(waiting(j)).toBe(0);
});

it('a change while the first send is on its way is sent next', () => {
  let j = started(record(fresh(), 'a', 1, EIGHT, T1), session());
  const sending = nextStep(j); // version 1 on its way…
  j = record(j, 'a', 1, TEN, T2); // …and the numbers change
  j = sent(j, 'a/1', sending?.kind === 'set' ? sending.record.version : 0);

  const again = nextStep(j);
  expect(again).toMatchObject({ kind: 'set', key: 'a/1' });
  expect(again?.kind === 'set' && again.record.entry).toEqual(TEN);
});

it('changing the numbers keeps the time it was ticked; a new tick takes a new time', () => {
  let j = record(fresh(), 'a', 1, EIGHT, T1);
  j = record(j, 'a', 1, TEN, T2);
  expect(j.sets['a/1']?.at).toBe(T1);

  j = record(j, 'a', 1, null, T2); // untick
  j = record(j, 'a', 1, EIGHT, T2); // tick again
  expect(j.sets['a/1']?.at).toBe(T2);
});

it('an untick is sent (to remove it) and no longer counts', () => {
  let j = started(record(fresh(), 'a', 1, EIGHT, T1), session());
  j = sent(j, 'a/1', 1);
  j = record(j, 'a', 1, null, T2);
  expect(loggedSets(j)).toEqual([]);
  expect(nextStep(j)).toMatchObject({ kind: 'set', key: 'a/1', record: { entry: null } });
});

it('unticking a set that was never ticked changes nothing', () => {
  const j = fresh();
  expect(record(j, 'a', 1, null, T1)).toBe(j);
});

it('a finished workout no longer changes', () => {
  const j = finishHere(record(fresh(), 'a', 1, EIGHT, T1), null, T2);
  expect(record(j, 'a', 2, EIGHT, T2)).toBe(j);
  expect(finishHere(j, 'too_hard', T2)).toBe(j);
});

it('sets the server already had join; where the phone changed one, the phone wins', () => {
  const j = started(record(fresh(), 'a', 1, TEN, T1), session([
    { planned_exercise_id: 'a', set_number: 1, reps: 8 },
    { planned_exercise_id: 'wu', set_number: 1, reps: 5 },
  ]));
  expect(j.sets['a/1']?.entry).toEqual(TEN);
  expect(j.sets['wu/1']).toMatchObject({ version: 1, sent: 1 });
  expect(nextStep(j)).toMatchObject({ kind: 'set', key: 'a/1' });
});

it('a refused change counts as dropped and is not sent again', () => {
  let j = started(record(fresh(), 'a', 1, EIGHT, T1), session());
  j = sent(j, 'a/1', 1, true);
  expect(j.dropped).toBe(1);
  expect(nextStep(j)).toBeNull();
});

it('reads back only a journal this app version wrote', () => {
  const j = record(fresh(), 'a', 1, EIGHT, T1);
  expect(parseJournal(JSON.stringify(j))).toEqual(j);
  expect(parseJournal(JSON.stringify({ ...j, v: 0 }))).toBeNull();
  expect(parseJournal('not json')).toBeNull();
  expect(parseJournal(null)).toBeNull();
});

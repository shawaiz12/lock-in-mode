/**
 * The workout journal (ADR 0033): everything done in the workout in progress, written on
 * the phone FIRST and sent to the API after. Online, "after" is a moment later; offline,
 * it's whenever the phone is back online. The player only ever reads the journal, so it
 * works the same with or without a connection.
 *
 *   begin -> record a set (tick, change, untick) ... -> finishHere -> synced (done)
 *
 * Each set remembers how many times it changed (`version`) and how many of those the
 * server has (`sent`). Different numbers = it still needs sending. A change made while
 * an older one is on its way just stays different, so it's sent next: nothing is lost
 * and nothing is sent twice for no reason.
 *
 * Pure functions on plain data, so it's tested without React, storage or a server.
 * .NET: like an outbox table (rows written in the same "transaction" as the change, sent
 * by a background worker), here one small JSON document.
 */
import type { components } from '@/api/schema';
import type { Entry } from '@/features/player/entry';

type Schemas = components['schemas'];
type Feedback = Schemas['Feedback'];
type Session = Schemas['SessionRead'];
type SessionResult = Schemas['SessionResult'];
type SetLog = Schemas['SetLogRead'];

/** Bump when the shape changes: an older journal on the phone is then read as none. */
export const JOURNAL_VERSION = 1;

export type SetRecord = {
  plannedExerciseId: string;
  setNumber: number;
  /** null: unticked (the server is told to remove it). */
  entry: Entry | null;
  /** When it was ticked on the phone (ISO time). Changing the numbers keeps it. */
  at: string;
  /** Changes made on the phone. */
  version: number;
  /** Changes the server has. */
  sent: number;
};

/** Why a journal can't be saved: the plan moved on (changed answers, a skip on another
 * phone), the sign-in ended, or the workout is gone on the server. */
export type Lost = 'plan_moved' | 'signed_out' | 'gone';

export type Journal = {
  v: typeof JOURNAL_VERSION;
  workoutId: string;
  /** "Workout 4", for the cards on the plan screen. */
  position: number;
  /** Known once the server has the start. */
  sessionId: string | null;
  /** When it was started on the phone (ISO time). */
  startedAt: string;
  sets: Record<string, SetRecord>;
  finish: { feedback: Feedback | null; at: string } | null;
  /** The server has the finish. */
  done: boolean;
  /** What the server answered to the finish: what moved up, the next workout. null when
   * the finish arrived but its answer didn't (it was finished already). */
  result: SessionResult | null;
  lost: Lost | null;
  /** Set changes the server refused (the workout was finished elsewhere). */
  dropped: number;
};

export function setKey(plannedExerciseId: string, setNumber: number): string {
  return `${plannedExerciseId}/${setNumber}`;
}

export function begin(workoutId: string, position: number, at: string): Journal {
  return {
    v: JOURNAL_VERSION,
    workoutId,
    position,
    sessionId: null,
    startedAt: at,
    sets: {},
    finish: null,
    done: false,
    result: null,
    lost: null,
    dropped: 0,
  };
}

/** Tick, change or untick (`entry` null) a set. A finished workout no longer changes. */
export function record(
  journal: Journal,
  plannedExerciseId: string,
  setNumber: number,
  entry: Entry | null,
  at: string,
): Journal {
  if (journal.finish || journal.lost) return journal;
  const key = setKey(plannedExerciseId, setNumber);
  const before = journal.sets[key];
  if (!before && entry === null) return journal; // unticking something never ticked
  const keepTime = entry !== null && before?.entry != null; // a change, not a new tick
  const next: SetRecord = {
    plannedExerciseId,
    setNumber,
    entry,
    at: keepTime && before ? before.at : at,
    version: (before?.version ?? 0) + 1,
    sent: before?.sent ?? 0,
  };
  return { ...journal, sets: { ...journal.sets, [key]: next } };
}

export function finishHere(journal: Journal, feedback: Feedback | null, at: string): Journal {
  if (journal.finish || journal.lost) return journal;
  return { ...journal, finish: { feedback, at } };
}

/** The sets that count, as the server would show them. */
export function loggedSets(journal: Journal): SetLog[] {
  return Object.values(journal.sets).flatMap((s) =>
    s.entry
      ? [
          {
            planned_exercise_id: s.plannedExerciseId,
            set_number: s.setNumber,
            reps: s.entry.reps,
            weight_kg: s.entry.weight_kg,
            seconds: s.entry.seconds,
          },
        ]
      : [],
  );
}

export function hasProgress(journal: Journal): boolean {
  return loggedSets(journal).length > 0 || journal.finish !== null;
}

/** Things the server doesn't have yet: the start, set changes, the finish. */
export function waiting(journal: Journal): number {
  if (journal.lost || journal.done) return 0;
  const sets = Object.values(journal.sets).filter((s) => s.version !== s.sent).length;
  return sets + (journal.sessionId === null ? 1 : 0) + (journal.finish ? 1 : 0);
}

// --- sending --------------------------------------------------------------------------

export type Step =
  | { kind: 'start' }
  | { kind: 'set'; key: string; record: SetRecord; sessionId: string }
  | { kind: 'finish'; sessionId: string; feedback: Feedback | null; at: string };

/** What to send next, in order: the start, then set changes, then the finish. */
export function nextStep(journal: Journal): Step | null {
  if (journal.lost || journal.done) return null;
  if (journal.sessionId === null) return { kind: 'start' };
  for (const [key, s] of Object.entries(journal.sets)) {
    if (s.version !== s.sent) return { kind: 'set', key, record: s, sessionId: journal.sessionId };
  }
  if (journal.finish) {
    return { kind: 'finish', sessionId: journal.sessionId, feedback: journal.finish.feedback, at: journal.finish.at };
  }
  return null;
}

/** The server has the start (POST /sessions). If it already had sets for this workout
 * (started on another phone, or before this app was reinstalled), those join the
 * journal; where this phone changed the same set, the phone's change wins. */
export function started(journal: Journal, session: Session): Journal {
  const sets = { ...journal.sets };
  for (const s of session.sets) {
    const key = setKey(s.planned_exercise_id, s.set_number);
    if (sets[key]) continue;
    sets[key] = {
      plannedExerciseId: s.planned_exercise_id,
      setNumber: s.set_number,
      entry: { reps: s.reps, weight_kg: s.weight_kg, seconds: s.seconds },
      at: session.started_at,
      version: 1,
      sent: 1,
    };
  }
  return { ...journal, sessionId: session.id, sets };
}

/** The server has `version` of this set (or refused it: `dropped`). */
export function sent(journal: Journal, key: string, version: number, dropped = false): Journal {
  const s = journal.sets[key];
  if (!s) return journal;
  return {
    ...journal,
    sets: { ...journal.sets, [key]: { ...s, sent: Math.max(s.sent, version) } },
    dropped: journal.dropped + (dropped ? 1 : 0),
  };
}

export function finished(journal: Journal, result: SessionResult | null): Journal {
  return { ...journal, done: true, result };
}

export function lose(journal: Journal, why: Lost): Journal {
  return { ...journal, lost: why };
}

/** A journal read back from storage, or null if it isn't one this app version knows. */
export function parseJournal(text: string | null): Journal | null {
  if (!text) return null;
  try {
    const value = JSON.parse(text) as Partial<Journal> | null;
    if (!value || value.v !== JOURNAL_VERSION || typeof value.workoutId !== 'string') return null;
    return value as Journal;
  } catch {
    return null;
  }
}

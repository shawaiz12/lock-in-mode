/**
 * Sending the journal (ADR 0033): one step at a time, in order, until nothing is left
 * or the connection goes. Every request is safe to send twice (POST /sessions continues
 * the open session, PUT replaces a set, a second finish answers "already finished"), so
 * a step whose answer was lost is simply sent again.
 *
 * What a failure means decides what happens next:
 *   no connection          -> stop, try again later (nothing changes)
 *   429 / 5xx              -> stop, try again later
 *   sign-in ended          -> the journal can't be saved (lost)
 *   plan moved on (start)  -> lost: this workout isn't the next one any more
 *   set refused (409/404)  -> that one change is dropped, the rest carries on
 *   already finished       -> done: the finish arrived earlier, only its answer didn't
 *
 * The API calls and the journal store come in as arguments, so this is tested with fakes.
 * .NET: like the background worker that drains an outbox, with a retry policy per error.
 */
import { ApiError, SignedOutError } from '@/api/problem';
import type { components } from '@/api/schema';
import { toSetLog } from '@/features/player/entry';

import { finished, type Journal, lose, nextStep, sent, started } from './journal';

type Schemas = components['schemas'];

export type SyncApi = {
  start(workoutId: string, startedAt: string): Promise<Schemas['SessionRead']>;
  logSet(
    where: { sessionId: string; plannedExerciseId: string; setNumber: number },
    body: Schemas['SetLogWrite'],
  ): Promise<unknown>;
  deleteSet(where: { sessionId: string; plannedExerciseId: string; setNumber: number }): Promise<void>;
  finish(sessionId: string, feedback: Schemas['Feedback'] | null, finishedAt: string): Promise<Schemas['SessionResult']>;
};

/** Why sending stopped. `offline` and `later` mean "try again"; the rest are final. */
export type SyncStop = 'nothing' | 'done' | 'lost' | 'offline' | 'later';

/** The journal as it is NOW (it changes while requests are on their way), and a way to
 * change it that always starts from the latest version. */
export type JournalAccess = {
  get(): Journal | null;
  update(workoutId: string, change: (journal: Journal) => Journal): void;
};

type Failure = 'offline' | 'later' | 'signed_out' | { status: number; code: string };

function failure(error: unknown): Failure {
  if (error instanceof SignedOutError) return 'signed_out';
  if (error instanceof ApiError) {
    if (error.status === 429 || error.status >= 500) return 'later';
    return { status: error.status, code: error.code };
  }
  // fetch throws a TypeError ("Network request failed") without a connection. Anything
  // else unexpected (a missing API address) is also worth retrying rather than losing.
  return error instanceof TypeError ? 'offline' : 'later';
}

export async function runSync(journal: JournalAccess, api: SyncApi): Promise<SyncStop> {
  for (;;) {
    const current = journal.get();
    if (!current) return 'nothing';
    const step = nextStep(current);
    if (!step) return current.done ? 'done' : current.lost ? 'lost' : 'nothing';
    const id = current.workoutId;
    try {
      if (step.kind === 'start') {
        const session = await api.start(id, current.startedAt);
        journal.update(id, (j) => started(j, session));
      } else if (step.kind === 'set') {
        const { record } = step;
        const where = {
          sessionId: step.sessionId,
          plannedExerciseId: record.plannedExerciseId,
          setNumber: record.setNumber,
        };
        if (record.entry) await api.logSet(where, { ...toSetLog(record.entry), logged_at: record.at });
        else await api.deleteSet(where);
        journal.update(id, (j) => sent(j, step.key, record.version));
      } else {
        const result = await api.finish(step.sessionId, step.feedback, step.at);
        journal.update(id, (j) => finished(j, result));
      }
    } catch (error) {
      const why = failure(error);
      if (why === 'offline' || why === 'later') return why;
      if (why === 'signed_out') {
        journal.update(id, (j) => lose(j, 'signed_out'));
        return 'lost';
      }
      if (step.kind === 'start') {
        // not_next_workout (the plan moved on) or not_found (the plan was replaced).
        journal.update(id, (j) => lose(j, 'plan_moved'));
        return 'lost';
      }
      if (why.code === 'session_not_found') {
        journal.update(id, (j) => lose(j, 'gone'));
        return 'lost';
      }
      if (step.kind === 'set') {
        // session_finished (finished elsewhere) or not_found / 422: this change can't be
        // saved. Drop it and carry on, so one bad set never blocks the rest.
        const { key, record } = step;
        journal.update(id, (j) => sent(j, key, record.version, true));
        continue;
      }
      // The finish: "already finished" means an earlier finish got there.
      journal.update(id, (j) => finished(j, null));
    }
  }
}

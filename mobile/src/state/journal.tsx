/**
 * The journal of the workout in progress, kept on the phone and sent to the API
 * (ADR 0033). The rules are pure (src/features/offline); this file adds what a running
 * app needs:
 *
 * - Saving: every change is written to the phone's storage AT ONCE (a synchronous
 *   write), before the screen even redraws. Close the app mid-set: the tick is there.
 * - Sending: `sync()` sends what's waiting, one run at a time. Asked again while a run
 *   is going, it runs once more after it, so a tick made at the last moment isn't missed.
 * - Trying again: without a connection (or a busy server) it tries again after 5 s,
 *   15 s, 30 s, then every minute; at once when the phone comes back online or the app
 *   comes back to the front.
 *
 * One journal at a time: the next workout needs this one sent first (his choice, ADR
 * 0033), because its numbers depend on how this one went.
 * .NET: like a singleton service owning an outbox file plus a BackgroundService that
 * drains it, with a Polly retry policy; screens subscribe to it like to an event.
 */
import { onlineManager } from '@tanstack/react-query';
import { createContext, type ReactNode, useContext, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';

import type { Feedback } from '@/api/endpoints';
import {
  begin as beginJournal,
  finishHere as finishJournal,
  type Journal,
  parseJournal,
  record as recordSet,
} from '@/features/offline/journal';
import { type JournalAccess, runSync, type SyncApi, type SyncStop } from '@/features/offline/sync';
import type { Entry } from '@/features/player/entry';

export const JOURNAL_KEY = 'lockin.journal';
const RETRY_MS = [5_000, 15_000, 30_000, 60_000];

/** The parts of expo-sqlite's key-value store this uses (faked in tests). */
export type KeyValue = {
  getItemSync(key: string): string | null;
  setItemSync(key: string, value: string): void;
  removeItemSync(key: string): boolean;
};

export type JournalSnapshot = {
  journal: Journal | null;
  /** Sending right now. */
  syncing: boolean;
  /** How the last run ended (null: none yet). `offline`/`later`: it will try again. */
  stop: SyncStop | null;
};

type Deps = {
  storage: KeyValue;
  api: SyncApi;
  /** Told after every change: the app refreshes the plan when a finish arrives. */
  onChange?: (before: Journal | null, after: Journal | null) => void;
};

export function createJournalStore({ storage, api, onChange }: Deps) {
  let journal: Journal | null = null;
  try {
    journal = parseJournal(storage.getItemSync(JOURNAL_KEY));
  } catch {
    journal = null;
  }
  let snapshot: JournalSnapshot = { journal, syncing: false, stop: null };
  const listeners = new Set<() => void>();
  let running: Promise<SyncStop> | null = null;
  let again = false;
  let retries = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function publish(patch: Partial<JournalSnapshot>) {
    snapshot = { ...snapshot, ...patch };
    for (const listener of listeners) listener();
  }

  function write(next: Journal | null) {
    const before = journal;
    journal = next;
    try {
      if (next) storage.setItemSync(JOURNAL_KEY, JSON.stringify(next));
      else storage.removeItemSync(JOURNAL_KEY);
    } catch {
      // A full or broken disk: keep going in memory. Sending still works.
    }
    publish({ journal: next });
    onChange?.(before, next);
  }

  const access: JournalAccess = {
    get: () => journal,
    update: (workoutId, change) => {
      if (journal && journal.workoutId === workoutId) write(change(journal));
    },
  };

  function stopTimer() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  function retryLater(stop: SyncStop) {
    stopTimer();
    if (stop !== 'offline' && stop !== 'later') {
      retries = 0;
      return;
    }
    const delay = RETRY_MS[Math.min(retries, RETRY_MS.length - 1)] ?? 60_000;
    retries += 1;
    timer = setTimeout(() => void sync(), delay);
  }

  /** Send what's waiting. Resolves with how it ended. */
  function sync(): Promise<SyncStop> {
    if (running) {
      again = true;
      return running;
    }
    stopTimer();
    if (!onlineManager.isOnline()) {
      // Known to be offline: don't even try. Coming back online sends it (attach()).
      if (snapshot.stop !== 'offline') publish({ stop: 'offline' });
      return Promise.resolve('offline');
    }
    publish({ syncing: true });
    running = (async () => {
      let stop: SyncStop;
      do {
        again = false;
        stop = await runSync(access, api);
      } while (again && stop !== 'offline' && stop !== 'later');
      return stop;
    })();
    const done = running;
    void done.then(
      (stop) => {
        running = null;
        publish({ syncing: false, stop });
        retryLater(stop);
        // Asked again in the moment between the run ending and this line: go once more.
        if (again && stop !== 'offline' && stop !== 'later') void sync();
      },
      () => {
        running = null;
        publish({ syncing: false, stop: 'later' });
        retryLater('later');
      },
    );
    return done;
  }

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    snapshot: () => snapshot,
    current: () => journal,
    sync,

    /** Start a new journal for this workout (it replaces a finished-and-sent one). */
    begin(workoutId: string, position: number, at: string) {
      write(beginJournal(workoutId, position, at));
    },
    /** Tick, change or untick (`entry` null) a set, then send it. */
    record(plannedExerciseId: string, setNumber: number, entry: Entry | null, at: string) {
      if (!journal) return;
      write(recordSet(journal, plannedExerciseId, setNumber, entry, at));
      void sync();
    },
    /** Finish here, then send everything. */
    finish(feedback: Feedback | null, at: string): Promise<SyncStop> {
      if (journal) write(finishJournal(journal, feedback, at));
      return sync();
    },
    /** The journal was seen through (result shown, or a lost one acknowledged). */
    clear() {
      write(null);
    },

    /** Try again when the phone comes back online or the app comes to the front.
     * Returns the clean-up (stops listening and any waiting retry). */
    attach(): () => void {
      const offOnline = onlineManager.subscribe((online) => {
        if (online) void sync();
      });
      const offApp = AppState.addEventListener('change', (state) => {
        if (state === 'active') void sync();
      });
      if (journal) void sync();
      return () => {
        offOnline();
        offApp.remove();
        stopTimer();
      };
    },
  };
}

export type JournalStore = ReturnType<typeof createJournalStore>;

const JournalContext = createContext<JournalStore | null>(null);

export function JournalProvider({ store, children }: { store: JournalStore; children: ReactNode }) {
  return <JournalContext.Provider value={store}>{children}</JournalContext.Provider>;
}

export function useJournalStore(): JournalStore {
  const store = useContext(JournalContext);
  if (!store) throw new Error('useJournalStore needs a JournalProvider (src/app/_layout.tsx)');
  return store;
}

/** The journal and how sending is going; the screen redraws when either changes. */
export function useJournal(): JournalSnapshot {
  const store = useJournalStore();
  return useSyncExternalStore(store.subscribe, store.snapshot);
}

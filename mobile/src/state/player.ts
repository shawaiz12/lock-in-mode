/**
 * The workout player's brain: which set is next, the rest and work timers, sending each
 * tick to the API, swaps, and finishing. The screen (src/app/workout/[id]/play.tsx) only
 * draws what this returns and calls its actions.
 *
 * - Where you are is never stored: it's worked out from what's logged (steps.ts
 *   `nextPosition`). Leave mid-workout, come back tomorrow: it picks up at the first set
 *   not done.
 * - Everything goes into the journal on the phone first (ADR 0033, src/state/journal.tsx)
 *   and is sent from there: online a moment later, offline once the phone is back. So a
 *   tick is never "not saved", and finishing works without a connection too: the results
 *   show once the finish reaches the server.
 * - Swaps need the server (it picks the replacement), so they need a connection.
 * - Timers store when they end (clock.ts). This hook re-reads them 4 times a second while
 *   one is running and acts when one is over: beep, buzz, log or move on.
 *
 * .NET/Unity: like a MonoBehaviour that owns the game state, with the pure rules in
 * plain C# classes it calls; React redraws the screen whenever the state changes.
 */
import { onlineManager, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  type BodyLimit,
  type BodyArea,
  type ExerciseDetail,
  type Feedback,
  getExercise,
  getWorkout,
  type PlannedExercise,
  sayWhereItHurts,
  swapExercise,
  type SwapReason,
  type WorkoutDetail,
} from '@/api/endpoints';
import { isApiError } from '@/api/problem';
import { hasProgress, type Lost, loggedSets, setKey, waiting } from '@/features/offline/journal';
import {
  type Clock,
  addSeconds,
  countdown,
  countInBeeps,
  isOver,
  pause,
  reading,
  resume,
  secondsDone,
  stopwatch,
} from '@/features/player/clock';
import { type Entry, isWeighted, prefill } from '@/features/player/entry';
import {
  buildStations,
  type Item,
  type Station,
  isDone,
  nextPosition,
  progress,
} from '@/features/player/steps';
import { useJournal, useJournalStore } from '@/state/journal';
import { useOnline } from '@/state/online';
import { offlineReady } from '@/state/persist';
import { keys } from '@/state/startup';
import type { Alerts } from '@/ui/alerts';

export type Phase =
  | { name: 'ready' }
  /** A timed move or a strength-test hold is running. */
  | { name: 'work'; key: string; clock: Clock }
  /** Resting after `after`. `chain`: when it ends, the next timed move starts by itself. */
  | { name: 'rest'; after: string; clock: Clock; chain: boolean };

/** One line to show for a few seconds: what a swap did, a save that failed. */
export type Notice = { text: string };

const TICK_MS = 250;
/** How long opening waits for the server's copy of the session before going on without. */
const OPEN_WAIT_MS = 4_000;
/** How long "How did that feel?" waits for the results before saying "saved here". */
const FINISH_WAIT_MS = 10_000;

/** Something here needs a connection first (ADR 0033). */
export class NeedsConnectionError extends Error {
  constructor(
    /** missing: not on the phone. stale: downloaded over 14 days ago. waiting: the last
     * workout isn't sent yet. swap: swapping asks the server. */
    readonly why: 'missing' | 'stale' | 'waiting' | 'swap',
  ) {
    super(`Needs a connection (${why})`);
    this.name = 'NeedsConnectionError';
  }
}

/** The journal can't be saved (the plan moved on, the sign-in ended). */
export class JournalLostError extends Error {
  constructor(readonly why: Lost) {
    super(`Can't be saved (${why})`);
    this.name = 'JournalLostError';
  }
}

const READY: Phase = { name: 'ready' };

const iso = (ms: number) => new Date(ms).toISOString();
const pause_ = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function withKey<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  next.add(value);
  return next;
}

/** Every exercise in a workout, once each: their library pages ("How to do it", which
 * moves are holds) are fetched with it, and kept on the phone for offline. */
export function exerciseIds(workout: WorkoutDetail | undefined): string[] {
  if (!workout) return [];
  const rows = [...workout.warm_up, ...workout.main, ...workout.finisher, ...workout.cool_down];
  return [...new Set(rows.map((row) => row.exercise.id))];
}

export function usePlayer(workoutId: string, alerts: Alerts, now: () => number = Date.now) {
  const queryClient = useQueryClient();
  const store = useJournalStore();
  const { journal, syncing, stop: lastSync } = useJournal();
  const online = useOnline();

  // --- the workout (saved on the phone, or fetched) ---------------------------------------
  const workout = useQuery({ queryKey: keys.workout(workoutId), queryFn: () => getWorkout(workoutId) });
  const ids = exerciseIds(workout.data);
  const details = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.exercise(id),
      queryFn: () => getExercise(id),
      staleTime: Infinity,
    })),
    combine: (results) => ({
      byId: new Map(
        results.flatMap((r, i) => (r.data && ids[i] ? [[ids[i], r.data] as const] : [])),
      ) as Map<string, ExerciseDetail>,
      // A library page that fails isn't a reason to stop the workout: the player falls
      // back to what the workout itself says (no "How to do it", weights only if known).
      // Offline, a page that isn't on the phone waits ("paused"): don't wait for it.
      settled: results.every((r) => !r.isPending || r.fetchStatus === 'paused'),
    }),
  });

  // --- the journal: this workout's sets, on the phone first ------------------------------
  const mine = journal?.workoutId === workoutId ? journal : null;
  // Another workout still waiting to be sent: the next one needs it sent first.
  const blocking = journal !== null && mine === null && !journal.done && !journal.lost;
  const [opening, setOpening] = useState(false);
  const begun = useRef(false);
  const [openedAt] = useState(now);
  const position_ = workout.data?.position;
  // Offline, only a copy downloaded in the last 14 days can start (ADR 0033).
  const copy = workout.data === undefined ? undefined : { data: workout.data, dataUpdatedAt: workout.dataUpdatedAt };
  const offlineCopy = online ? 'ready' : offlineReady(copy, openedAt);
  const openError = !mine && offlineCopy !== 'ready' ? new NeedsConnectionError(offlineCopy) : null;
  useEffect(() => {
    // Opening the player starts the workout: a new journal, sent at once if online. At
    // most once per visit (leaving after "done" must not start it again).
    if (begun.current || mine || blocking || position_ === undefined || offlineCopy !== 'ready') return;
    begun.current = true;
    store.begin(workoutId, position_, iso(now()));
    setOpening(true);
    // Online, wait a moment for the server's copy (continuing: sets ticked earlier).
    void Promise.race([store.sync(), pause_(OPEN_WAIT_MS)]).finally(() => setOpening(false));
  }, [mine, blocking, position_, offlineCopy, workoutId, store, now]);

  const [localDone, setLocalDone] = useState<ReadonlySet<string>>(new Set());
  const [passed, setPassed] = useState<ReadonlySet<string>>(new Set());
  const [drafts, setDrafts] = useState<ReadonlyMap<string, Entry>>(new Map());
  const [phase, setPhase] = useState<Phase>(READY);
  const [nowMs, setNowMs] = useState(now);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [askWhere, setAskWhere] = useState<{ exerciseId: string; name: string } | null>(null);
  const [suggestLimit, setSuggestLimit] = useState<BodyLimit | null>(null);
  const [finishing, setFinishing] = useState(false);

  const logged = useMemo(
    () => new Map((mine ? loggedSets(mine) : []).map((s) => [setKey(s.planned_exercise_id, s.set_number), s])),
    [mine],
  );

  // --- derived -------------------------------------------------------------------------
  const isTimed = (id: string) => details.byId.get(id)?.is_timed;
  const stations: Station[] = useMemo(
    () => (workout.data && details.settled ? buildStations(workout.data, (id) => details.byId.get(id)?.is_timed) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- byId is rebuilt each render; settled + data say when it changed
    [workout.data, details.settled, details.byId.size],
  );
  const loggedKeys = useMemo(() => new Set(logged.keys()), [logged]);
  const position = nextPosition(stations, loggedKeys, localDone, passed);
  const current = position ? stations[position.station] : undefined;
  const currentItem = position && current ? current.items[position.item] : undefined;
  const totals = progress(stations, loggedKeys);

  const weighted = (row: PlannedExercise) =>
    isWeighted(details.byId.get(row.exercise.id)) || row.weight_kg !== null || row.last?.weight_kg != null;

  /** What a set shows and what one tap sends: an edit, what was logged, or the pre-fill. */
  function entryFor(item: Item): Entry {
    const draft = drafts.get(item.key);
    if (draft) return draft;
    const done = logged.get(item.key);
    if (done) return { reps: done.reps, weight_kg: done.weight_kg, seconds: done.seconds };
    return prefill(item, weighted(item.exercise));
  }

  // --- saving --------------------------------------------------------------------------
  /** Into the journal (on the phone at once), then sent. `entry` null: untick. */
  function save(item: Item, entry: Entry | null) {
    store.record(item.exercise.id, item.set, entry, iso(now()));
  }

  // --- moving through the workout ------------------------------------------------------
  /** After `item` is done (or passed over): rest, start the next timed move, or wait. */
  function moveOn(item: Item, done: { logged: ReadonlySet<string>; local: ReadonlySet<string> }, chain: boolean) {
    const t = now();
    setNowMs(t);
    const next = nextPosition(stations, done.logged, done.local, passed);
    const nextItem = next ? stations[next.station]?.items[next.item] : undefined;
    const sameStation = next !== null && position !== null && next.station === position.station;
    const keepsGoing = chain && sameStation && nextItem?.autoNext === true;
    if (item.restAfter > 0 && next !== null) {
      setPhase({ name: 'rest', after: item.key, clock: countdown(item.restAfter, t), chain: keepsGoing });
    } else if (keepsGoing && nextItem) {
      setPhase({ name: 'work', key: nextItem.key, clock: countdown(nextItem.exercise.seconds ?? 0, t) });
    } else {
      setPhase(READY);
    }
  }

  /** ✓ on a set: show it done at once, send it, then rest or move on. */
  function tick(item: Item, entry: Entry, chain = false) {
    alerts.ticked();
    setDrafts((map) => {
      if (!map.has(item.key)) return map;
      const copy = new Map(map);
      copy.delete(item.key);
      return copy;
    });
    if (item.kind === 'practice') {
      const local = withKey(localDone, item.key);
      setLocalDone(local);
      moveOn(item, { logged: loggedKeys, local }, chain);
      return;
    }
    save(item, entry);
    moveOn(item, { logged: new Set(loggedKeys).add(item.key), local: localDone }, chain);
  }

  /** "Start": a countdown for timed moves, a stopwatch for a strength-test hold. */
  function start(item: Item) {
    const t = now();
    setNowMs(t);
    const clock = item.kind === 'open_hold' ? stopwatch(t) : countdown(item.exercise.seconds ?? 0, t);
    setPhase({ name: 'work', key: item.key, clock });
  }

  /** "Stop" on a running move: log the seconds really done (nothing if under a second). */
  function stop() {
    if (phase.name !== 'work') return;
    const item = findItem(phase.key);
    const seconds = secondsDone(phase.clock, now());
    if (!item || seconds < 1) {
      setPhase(READY);
      return;
    }
    tick(item, { ...entryFor(item), seconds });
  }

  /** Pass over the current move without logging it (warm-up, a HIIT move). */
  function skipItem(item: Item) {
    const local = withKey(localDone, item.key);
    setLocalDone(local);
    const running = phase.name === 'work' && phase.key === item.key;
    moveOn({ ...item, restAfter: 0 }, { logged: loggedKeys, local }, running && item.autoNext);
  }

  /** "Skip exercise": leave this screen's remaining sets undone (half counts). */
  function skipStation(station: Station) {
    setPassed((set) => withKey(set, station.key));
    setPhase(READY);
  }

  function untick(item: Item) {
    if (!logged.has(item.key)) return;
    save(item, null);
    if (phase.name === 'rest' && phase.after === item.key) setPhase(READY);
  }

  /** Change a set: before it's done (a draft), or after (sent again: PUT replaces it). */
  function edit(item: Item, entry: Entry) {
    if (logged.has(item.key)) {
      save(item, entry);
    } else {
      setDrafts((map) => new Map(map).set(item.key, entry));
    }
  }

  function findItem(key: string): Item | undefined {
    for (const station of stations) {
      const found = station.items.find((it) => it.key === key);
      if (found) return found;
    }
    return undefined;
  }

  function endRest() {
    if (phase.name !== 'rest') return;
    const next = nextPosition(stations, loggedKeys, localDone, passed);
    const nextItem = next ? stations[next.station]?.items[next.item] : undefined;
    if (phase.chain && nextItem?.autoNext) {
      const t = now();
      setNowMs(t);
      setPhase({ name: 'work', key: nextItem.key, clock: countdown(nextItem.exercise.seconds ?? 0, t) });
    } else {
      setPhase(READY);
    }
  }

  const togglePause = () =>
    setPhase((p) => {
      if (p.name === 'ready') return p;
      const t = now();
      const running = p.clock.kind === 'countdown' ? p.clock.endsAt !== null : p.clock.startedAt !== null;
      return { ...p, clock: running ? pause(p.clock, t) : resume(p.clock, t) };
    });

  const addRest = (seconds: number) =>
    setPhase((p) => (p.name === 'rest' ? { ...p, clock: addSeconds(p.clock, seconds, now()) } : p));

  // --- the clock -----------------------------------------------------------------------
  const running = phase.name !== 'ready';
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNowMs(now()), TICK_MS);
    return () => clearInterval(timer);
  }, [running, now]);

  // Act on the clock with the latest state (the functions above change every render).
  const latest = useRef({ phase, tick, endRest, findItem, entryFor, alerts });
  latest.current = { phase, tick, endRest, findItem, entryFor, alerts };
  const lastReading = useRef<{ key: string; ms: number } | null>(null);
  useEffect(() => {
    const { phase: p, alerts: a } = latest.current;
    if (p.name === 'ready' || p.clock.kind !== 'countdown') {
      lastReading.current = null;
      return;
    }
    const id = p.name === 'work' ? `work:${p.key}` : `rest:${p.after}`;
    const ms = reading(p.clock, nowMs);
    const before = lastReading.current?.key === id ? lastReading.current.ms : Infinity;
    lastReading.current = { key: id, ms };
    if (countInBeeps(before, ms).length > 0 && ms > 0) a.countIn();
    if (!isOver(p.clock, nowMs)) return;
    a.done();
    if (p.name === 'rest') {
      latest.current.endRest();
      return;
    }
    const item = latest.current.findItem(p.key);
    if (item) latest.current.tick(item, { ...latest.current.entryFor(item), seconds: item.exercise.seconds }, item.autoNext);
  }, [nowMs]);

  // --- swaps (ADR 0020) ----------------------------------------------------------------
  const swap = useMutation({
    networkMode: 'always', // offline it fails at once with a clear message, never waits
    mutationFn: async ({ row, reason }: { row: PlannedExercise; reason: SwapReason }) => {
      // The server works out the sets left from what it has: send everything first.
      await store.sync();
      const now_ = store.current();
      if (!onlineManager.isOnline() || !now_ || now_.sessionId === null || waiting(now_) > 0) {
        throw new NeedsConnectionError('swap');
      }
      return swapExercise(workoutId, row.id, row.exercise.id, reason);
    },
    onSuccess: (result, { reason }) => {
      queryClient.setQueryData(keys.workout(workoutId), result.workout);
      setPhase(READY);
      const out = result.swapped_out.name;
      if (result.left_out) setNotice({ text: `Nothing else safe for ${out}, so we've left it out.` });
      else if (result.swapped_in) setNotice({ text: `${out} → ${result.swapped_in.name}` });
      else setNotice({ text: `${out} is swapped out.` });
      if (reason === 'hurts') setAskWhere({ exerciseId: result.swapped_out.id, name: out });
    },
    onError: (error) => {
      if (error instanceof NeedsConnectionError) {
        setNotice({ text: 'Swapping needs a connection. Your sets are safe on this phone.' });
      } else if (isApiError(error, 'no_other_exercise')) {
        setNotice({ text: 'Nothing else does the same job for you, so this one stays today.' });
      } else if (isApiError(error, 'exercise_changed')) {
        void queryClient.invalidateQueries({ queryKey: keys.workout(workoutId) });
      } else {
        setNotice({ text: "Couldn't swap it. Check your connection and try again." });
      }
    },
  });

  const where = useMutation({
    networkMode: 'always',
    mutationFn: ({ exerciseId, area }: { exerciseId: string; area: BodyArea }) =>
      sayWhereItHurts(exerciseId, area),
    onSuccess: (limit) => {
      if (limit) setSuggestLimit(limit);
    },
    onSettled: () => setAskWhere(null),
  });

  // --- finishing -----------------------------------------------------------------------
  /** Into the journal, then sent. Waits a little for the results; offline, the play
   * screen says it's saved on the phone instead. */
  function finish(feedback: Feedback | null) {
    if (!mine || mine.finish || finishing) return;
    setPhase(READY);
    setFinishing(true);
    void Promise.race([store.finish(feedback, iso(now())), pause_(FINISH_WAIT_MS)]).finally(() =>
      setFinishing(false),
    );
  }

  // Sets the server doesn't have yet, worth a word when they can't be sent right now.
  const unsent = mine ? Object.values(mine.sets).filter((s) => s.version !== s.sent).length : 0;
  const stuck = !online || lastSync === 'offline' || lastSync === 'later';

  const lost = mine?.lost && !hasProgress(mine) ? new JournalLostError(mine.lost) : null;
  const missing = workout.isPending && !online ? new NeedsConnectionError('missing') : null;
  const error =
    workout.error ?? openError ?? missing ?? (blocking ? new NeedsConnectionError('waiting') : null) ?? lost;
  const loading = error === null && (workout.isPending || !details.settled || opening || mine === null);

  return {
    loading,
    error,
    retryLoading: () => {
      void workout.refetch();
    },
    /** Leave a journal that can't be saved, so the next visit starts cleanly. */
    dropLost: () => {
      if (mine?.lost) store.clear();
    },
    workout: workout.data,
    stations,
    position,
    current,
    currentItem,
    totals,
    phase,
    nowMs,
    isDone: (item: Item) => isDone(item, loggedKeys, localDone),
    isTimed,
    detail: (exerciseId: string) => details.byId.get(exerciseId),
    weighted,
    entryFor,
    online,
    /** Sets saved on this phone that can't be sent right now. */
    waitingSets: stuck && !syncing ? unsent : 0,
    syncNow: () => void store.sync(),
    notice,
    clearNotice: () => setNotice(null),
    askWhere,
    answerWhere: (area: BodyArea | null) => {
      if (!askWhere || area === null) setAskWhere(null);
      else where.mutate({ exerciseId: askWhere.exerciseId, area });
    },
    suggestLimit,
    tick,
    start,
    stop,
    skipItem,
    skipStation,
    untick,
    edit,
    endRest,
    togglePause,
    addRest,
    swap: (row: PlannedExercise, reason: SwapReason) => swap.mutate({ row, reason }),
    swapping: swap.isPending,
    finish,
    finishing,
    /** Finished on this phone. */
    finished: mine?.finish != null,
    /** The finish reached the server. */
    done: mine?.done === true,
    /** What the server answered (null if that answer was lost on the way). */
    result: mine?.done ? mine.result : null,
    /** The workout was seen through: forget the journal. */
    close: () => store.clear(),
  };
}

export type Player = ReturnType<typeof usePlayer>;

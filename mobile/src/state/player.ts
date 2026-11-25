/**
 * The workout player's brain: which set is next, the rest and work timers, sending each
 * tick to the API, swaps, and finishing. The screen (src/app/workout/[id]/play.tsx) only
 * draws what this returns and calls its actions.
 *
 * - Where you are is never stored: it's worked out from what's logged (steps.ts
 *   `nextPosition`). Leave mid-workout, come back tomorrow: it picks up at the first set
 *   not done, because the server keeps the open session (ADR 0018).
 * - A tick shows as done at once and is sent in the background. Sends for the same set
 *   go one after another (tick, then untick, never the other way round). A send that
 *   fails is kept and offered again ("Not saved. Retry"); finishing waits for all of them.
 * - Timers store when they end (clock.ts). This hook re-reads them 4 times a second while
 *   one is running and acts when one is over: beep, buzz, log or move on.
 *
 * .NET/Unity: like a MonoBehaviour that owns the game state, with the pure rules in
 * plain C# classes it calls; React redraws the screen whenever the state changes.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  type BodyLimit,
  type BodyArea,
  deleteSet,
  type ExerciseDetail,
  type Feedback,
  finishSession,
  getExercise,
  getWorkout,
  logSet,
  type PlannedExercise,
  type SessionResult,
  type SetLog,
  sayWhereItHurts,
  startSession,
  swapExercise,
  type SwapReason,
  type WorkoutDetail,
} from '@/api/endpoints';
import { isApiError } from '@/api/problem';
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
import { type Entry, isWeighted, prefill, toSetLog } from '@/features/player/entry';
import {
  buildStations,
  type Item,
  type Station,
  isDone,
  nextPosition,
  progress,
} from '@/features/player/steps';
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

/** Finishing was asked for while some sets still aren't saved. */
export class UnsavedSetsError extends Error {
  constructor() {
    super('Some sets aren’t saved yet. Retry them first.');
    this.name = 'UnsavedSetsError';
  }
}
const READY: Phase = { name: 'ready' };

function withKey<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  next.add(value);
  return next;
}

function exerciseIds(workout: WorkoutDetail | undefined): string[] {
  if (!workout) return [];
  const rows = [...workout.warm_up, ...workout.main, ...workout.finisher, ...workout.cool_down];
  return [...new Set(rows.map((row) => row.exercise.id))];
}

function asLog(item: Item, entry: Entry): SetLog {
  return {
    planned_exercise_id: item.exercise.id,
    set_number: item.set,
    reps: entry.reps,
    weight_kg: entry.weight_kg,
    seconds: entry.seconds,
  };
}

export function usePlayer(workoutId: string, alerts: Alerts, now: () => number = Date.now) {
  const queryClient = useQueryClient();

  // --- what the server has -------------------------------------------------------------
  const workout = useQuery({ queryKey: keys.workout(workoutId), queryFn: () => getWorkout(workoutId) });
  // POST /sessions starts the workout, or continues it: the same answer every time, so it
  // can be read like a query. Never refetched by itself: this screen owns the sets now.
  const session = useQuery({
    queryKey: keys.playing(workoutId),
    queryFn: () => startSession(workoutId),
    staleTime: Infinity,
    gcTime: 0,
  });
  // The plan screen asks "is a workout open?": it is now.
  const started = session.isSuccess;
  useEffect(() => {
    if (started) void queryClient.invalidateQueries({ queryKey: keys.openSession });
  }, [started, queryClient]);
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
      settled: results.every((r) => !r.isPending),
    }),
  });

  // --- what happened on this phone -----------------------------------------------------
  const [logged, setLogged] = useState<Map<string, SetLog> | null>(null);
  const [localDone, setLocalDone] = useState<ReadonlySet<string>>(new Set());
  const [passed, setPassed] = useState<ReadonlySet<string>>(new Set());
  const [drafts, setDrafts] = useState<ReadonlyMap<string, Entry>>(new Map());
  const [unsaved, setUnsaved] = useState<ReadonlyMap<string, { item: Item; entry: Entry | null }>>(
    new Map(),
  );
  const [phase, setPhase] = useState<Phase>(READY);
  const [nowMs, setNowMs] = useState(now);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [askWhere, setAskWhere] = useState<{ exerciseId: string; name: string } | null>(null);
  const [suggestLimit, setSuggestLimit] = useState<BodyLimit | null>(null);
  const sends = useRef(new Map<string, Promise<void>>());
  // Sets whose last send failed, known at once (state only shows after a redraw):
  // finishing checks this after waiting for every send.
  const failed = useRef(new Set<string>());

  // The sets the server already had (continuing a workout), once. Set while drawing,
  // React's way to start state from data that arrives later (no extra effect pass).
  const sessionId = session.data?.id;
  if (session.data && logged === null) {
    setLogged(new Map(session.data.sets.map((s) => [`${s.planned_exercise_id}/${s.set_number}`, s])));
  }

  // --- derived -------------------------------------------------------------------------
  const isTimed = (id: string) => details.byId.get(id)?.is_timed;
  const stations: Station[] = useMemo(
    () => (workout.data && details.settled ? buildStations(workout.data, (id) => details.byId.get(id)?.is_timed) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- byId is rebuilt each render; settled + data say when it changed
    [workout.data, details.settled, details.byId.size],
  );
  const loggedKeys = useMemo(() => new Set(logged?.keys() ?? []), [logged]);
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
    const done = logged?.get(item.key);
    if (done) return { reps: done.reps, weight_kg: done.weight_kg, seconds: done.seconds };
    return prefill(item, weighted(item.exercise));
  }

  // --- sending -------------------------------------------------------------------------
  function send(item: Item, entry: Entry | null) {
    if (!sessionId) return;
    const where = { sessionId, plannedExerciseId: item.exercise.id, setNumber: item.set };
    const previous = sends.current.get(item.key) ?? Promise.resolve();
    const next = previous.then(async () => {
      try {
        if (entry) await logSet(where, toSetLog(entry));
        else await deleteSet(where);
        failed.current.delete(item.key);
        setUnsaved((map) => {
          if (!map.has(item.key)) return map;
          const copy = new Map(map);
          copy.delete(item.key);
          return copy;
        });
      } catch {
        failed.current.add(item.key);
        setUnsaved((map) => new Map(map).set(item.key, { item, entry }));
      }
    });
    sends.current.set(item.key, next);
  }

  function retryUnsaved() {
    for (const { item, entry } of unsaved.values()) send(item, entry);
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
    const nextLogged = new Map(logged ?? []).set(item.key, asLog(item, entry));
    setLogged(nextLogged);
    send(item, entry);
    moveOn(item, { logged: new Set(nextLogged.keys()), local: localDone }, chain);
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
    if (!logged?.has(item.key)) return;
    const copy = new Map(logged);
    copy.delete(item.key);
    setLogged(copy);
    send(item, null);
    if (phase.name === 'rest' && phase.after === item.key) setPhase(READY);
  }

  /** Change a set: before it's done (a draft), or after (sent again: PUT replaces it). */
  function edit(item: Item, entry: Entry) {
    if (logged?.has(item.key)) {
      setLogged(new Map(logged).set(item.key, asLog(item, entry)));
      send(item, entry);
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
    mutationFn: ({ row, reason }: { row: PlannedExercise; reason: SwapReason }) =>
      swapExercise(workoutId, row.id, row.exercise.id, reason),
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
      if (isApiError(error, 'no_other_exercise')) {
        setNotice({ text: 'Nothing else does the same job for you, so this one stays today.' });
      } else if (isApiError(error, 'exercise_changed')) {
        void queryClient.invalidateQueries({ queryKey: keys.workout(workoutId) });
      } else {
        setNotice({ text: "Couldn't swap it. Check your connection and try again." });
      }
    },
  });

  const where = useMutation({
    mutationFn: ({ exerciseId, area }: { exerciseId: string; area: BodyArea }) =>
      sayWhereItHurts(exerciseId, area),
    onSuccess: (limit) => {
      if (limit) setSuggestLimit(limit);
    },
    onSettled: () => setAskWhere(null),
  });

  // --- finishing -----------------------------------------------------------------------
  const finish = useMutation({
    mutationFn: async (feedback: Feedback | null): Promise<SessionResult> => {
      if (!sessionId) throw new Error('No session');
      await Promise.all(sends.current.values());
      // Never finish with a set missing: finished sets are locked (409 session_finished).
      if (failed.current.size > 0) throw new UnsavedSetsError();
      return finishSession(sessionId, feedback);
    },
    onSuccess: () => {
      setPhase(READY);
      void queryClient.invalidateQueries({ queryKey: keys.plan });
      void queryClient.invalidateQueries({ queryKey: keys.openSession });
      void queryClient.invalidateQueries({ queryKey: keys.workout(workoutId) });
    },
  });

  const loading = workout.isPending || session.isPending || !details.settled || (session.isSuccess && logged === null);
  const error = workout.error ?? session.error ?? null;

  return {
    loading,
    error,
    retryLoading: () => {
      void workout.refetch();
      void session.refetch();
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
    unsaved: unsaved.size,
    retryUnsaved,
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
    finish: (feedback: Feedback | null) => finish.mutate(feedback),
    finishing: finish.isPending,
    finishError: finish.error,
    result: finish.data,
  };
}

export type Player = ReturnType<typeof usePlayer>;

/**
 * The workout player's screens (ADR 0032), drawn from what `usePlayer` returns
 * (src/state/player.ts). Nothing here decides anything: it shows and it forwards taps.
 *
 *   PlayerView    one station at a time: the current set, the timer or rest, the sets
 *   EditSheet     − / + for reps, kg, seconds (a set before or after it's ticked)
 *   MoreSheet     how to do it, "this hurts", "show another", skip, finish now
 *   FeedbackView  "How did that feel?" (one tap, or skip)
 *   ResultView    what moved up or back, the strength test, what's next
 *   SavedView     finished offline: saved on the phone, results once it's sent (ADR 0033)
 */
import { useEffect, useRef, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import type { BodyArea, BodyLimit, PlannedExercise, SessionResult } from '@/api/endpoints';
import { formatClock, reading } from '@/features/player/clock';
import { type Entry, entryText, isReady, step, targetText, weightStep } from '@/features/player/entry';
import {
  finishSubtitle,
  finishTitle,
  intervalsLine,
  isStepUp,
  limitQuestion,
  placementLine,
  progressLine,
} from '@/features/player/result';
import type { Item, Station } from '@/features/player/steps';
import { coachLine, partLabel, SAFETY_LINE, setLabel, upNext, waitingLine } from '@/features/player/words';
import { keptNowLine, newBestLine } from '@/features/week/words';
import { CAPPED_LINE, levelLine, levelShare, thousands, xpItemLine } from '@/features/xp/words';
import type { Player } from '@/state/player';
import {
  Body,
  Card,
  Choice,
  Label,
  LockInButton,
  OutlineButton,
  ProgressBar,
  Screen,
  Sheet,
  SmallKey,
  Stepper,
  TextButton,
  Tick,
  Title,
} from '@/ui/kit';
import { font, makeStyles, space, usePalette } from '@/ui/theme';
import { celebrate, Confetti, CountUp, FadeIn, FillBar, useSteps } from '@/ui/reveal';
import { ReminderOffer } from '@/ui/week';

// --- the player --------------------------------------------------------------------------

export function PlayerView({
  player,
  onLeave,
  onFinishNow,
}: {
  player: Player;
  onLeave: () => void;
  onFinishNow: () => void;
}) {
  const styles = useStyles();
  const { current: station, currentItem: item, phase, totals } = player;
  const [editing, setEditing] = useState<Item | null>(null);
  const [more, setMore] = useState(false);
  const [howTo, setHowTo] = useState<PlannedExercise | null>(null);
  if (!station || !item) return null;

  const resting = phase.name === 'rest';
  const working = phase.name === 'work' && phase.key === item.key ? phase : null;
  const entry = player.entryFor(item);

  return (
    <Screen
      footer={
        <MainAction
          player={player}
          station={station}
          item={item}
          entry={entry}
          working={working !== null}
          onEdit={() => setEditing(item)}
        />
      }
    >
      <View style={styles.topBar}>
        <SmallKey title="‹ Leave" onPress={onLeave} />
        <Text style={styles.count}>
          {totals.done} of {totals.total} sets
        </Text>
        <SmallKey title="More" onPress={() => setMore(true)} />
      </View>
      <ProgressBar value={totals.total === 0 ? 0 : totals.done / totals.total} />

      {player.waitingSets > 0 ? (
        <Card>
          <Body muted>{waitingLine(player.waitingSets)}</Body>
          {player.online ? <TextButton title="Try now" onPress={player.syncNow} /> : null}
        </Card>
      ) : null}

      {player.notice ? (
        <Card>
          <Body>{player.notice.text}</Body>
          <TextButton title="OK" onPress={player.clearNotice} />
        </Card>
      ) : null}

      {player.askWhere ? <WhereItHurts name={player.askWhere.name} onAnswer={player.answerWhere} /> : null}

      {resting ? (
        <RestCard player={player} station={station} item={item} />
      ) : null}

      <Label>{partLabel(station.part)}</Label>
      <Title>{station.title}</Title>
      {station.exercises.length > 1 ? (
        <Body muted>{station.exercises.map((row) => row.exercise.name).join(' · ')}</Body>
      ) : null}

      {!resting ? (
        <Card style={styles.current}>
          {station.exercises.length > 1 || station.layout === 'sequence' ? (
            <Text style={styles.exerciseName}>{item.exercise.exercise.name}</Text>
          ) : null}
          {setLabel(item, station) ? <Label>{setLabel(item, station)}</Label> : null}
          <Text style={styles.target}>{targetText(item)}</Text>
          {coachLine(item) ? <Body muted>{coachLine(item)}</Body> : null}
          {working ? (
            <WorkClock player={player} />
          ) : item.kind !== 'practice' ? (
            <EntryBoxes entry={entry} onEdit={() => setEditing(item)} />
          ) : null}
        </Card>
      ) : null}

      <SetList player={player} station={station} onEdit={setEditing} />

      <Body muted>{SAFETY_LINE}</Body>

      <EditSheet player={player} item={editing} onClose={() => setEditing(null)} />
      <MoreSheet
        visible={more}
        station={station}
        player={player}
        onClose={() => setMore(false)}
        onHowTo={(row) => {
          setMore(false);
          setHowTo(row);
        }}
        onFinishNow={() => {
          setMore(false);
          onFinishNow();
        }}
      />
      <HowToSheet player={player} row={howTo} onClose={() => setHowTo(null)} />
    </Screen>
  );
}

/** The set's numbers, big enough to read mid-set. Tapping any of them changes them. */
function EntryBoxes({ entry, onEdit }: { entry: Entry; onEdit: () => void }) {
  const styles = useStyles();
  const boxes: [string, string][] = [];
  if (entry.weight_kg !== null) boxes.push([String(entry.weight_kg), 'kg']);
  if (entry.reps !== null) boxes.push([String(entry.reps), entry.reps === 1 ? 'rep' : 'reps']);
  if (entry.seconds !== null) boxes.push([String(entry.seconds), 'seconds']);
  return (
    <View style={styles.entryArea}>
      <Text style={styles.entryHint}>Tap a number to change it</Text>
      <View style={styles.boxes}>
        {boxes.length === 0 ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Change the numbers"
            onPress={onEdit}
            style={({ pressed }) => [styles.box, pressed && styles.boxDown]}
          >
            <Text style={styles.boxEmpty}>Tap to fill in</Text>
          </Pressable>
        ) : (
          boxes.map(([value, unit]) => (
            <Pressable
              key={unit}
              accessibilityRole="button"
              accessibilityLabel="Change the numbers"
              accessibilityValue={{ text: entryText(entry) }}
              onPress={onEdit}
              style={({ pressed }) => [styles.box, pressed && styles.boxDown]}
            >
              <Text style={styles.boxValue}>{value}</Text>
              <Text style={styles.boxUnit}>{unit}</Text>
            </Pressable>
          ))
        )}
      </View>
    </View>
  );
}

function MainAction({
  player,
  station,
  item,
  entry,
  working,
  onEdit,
}: {
  player: Player;
  station: Station;
  item: Item;
  entry: Entry;
  working: boolean;
  onEdit: () => void;
}) {
  const styles = useStyles();
  if (player.phase.name === 'rest') {
    return (
      <View style={styles.row}>
        <OutlineButton title="+15 s" onPress={() => player.addRest(15)} />
        <OutlineButton title="Skip rest" onPress={player.endRest} />
      </View>
    );
  }
  if (working) {
    const auto = item.autoNext;
    return (
      <View style={styles.actions}>
        <View style={styles.row}>
          <OutlineButton title={paused(player) ? 'Resume' : 'Pause'} onPress={player.togglePause} />
          {auto ? <OutlineButton title="Skip move" onPress={() => player.skipItem(item)} /> : null}
        </View>
        <LockInButton title={item.kind === 'open_hold' ? 'Stop: log it' : 'Stop early'} onPress={player.stop} />
      </View>
    );
  }
  switch (item.kind) {
    case 'timed':
      return (
        <LockInButton
          title={
            item.autoNext && station.items[0]?.key === item.key
              ? `Lock In: start ${station.title === 'HIIT' ? 'HIIT' : station.title.toLowerCase()}`
              : `Start ${targetText(item)}`
          }
          onPress={() => player.start(item)}
        />
      );
    case 'open_hold':
      return <LockInButton title="Start the hold" onPress={() => player.start(item)} />;
    case 'open_reps':
      return isReady(item, entry) ? (
        <LockInButton title={`✓ Save ${entryText(entry)}`} onPress={() => player.tick(item, entry)} />
      ) : (
        <LockInButton title="How many did you do?" onPress={onEdit} />
      );
    case 'practice':
      return <LockInButton title="✓ Warm-up set done" onPress={() => player.tick(item, entry)} />;
    case 'reps':
      return <LockInButton title={`✓ ${entryText(entry)}`} onPress={() => player.tick(item, entry)} />;
  }
}

function paused(player: Player): boolean {
  const { phase } = player;
  if (phase.name === 'ready') return false;
  return phase.clock.kind === 'countdown' ? phase.clock.endsAt === null : phase.clock.startedAt === null;
}

function WorkClock({ player }: { player: Player }) {
  const styles = useStyles();
  if (player.phase.name !== 'work') return null;
  const { clock } = player.phase;
  const ms = reading(clock, player.nowMs);
  return (
    <Text style={styles.clock} accessibilityRole="timer">
      {formatClock(ms, clock.kind === 'countdown')}
    </Text>
  );
}

function RestCard({ player, station, item }: { player: Player; station: Station; item: Item }) {
  const styles = useStyles();
  if (player.phase.name !== 'rest') return null;
  const ms = reading(player.phase.clock, player.nowMs);
  return (
    <Card style={styles.rest}>
      <Label>{paused(player) ? 'Rest (paused)' : 'Rest'}</Label>
      <Text style={styles.clock} accessibilityRole="timer">
        {formatClock(ms, true)}
      </Text>
      <Body muted>{upNext(item, station)}</Body>
    </Card>
  );
}

function SetList({ player, station, onEdit }: { player: Player; station: Station; onEdit: (item: Item) => void }) {
  const styles = useStyles();
  const items = station.items.filter((it) => it.kind !== 'practice' || !player.isDone(it));
  if (items.length <= 1) return null;
  return (
    <View style={styles.sets}>
      {items.map((it) => {
        const done = player.isDone(it);
        const isCurrent = it.key === player.currentItem?.key;
        const label = setLabel(it, station);
        const name = station.exercises.length > 1 || station.layout === 'sequence' ? it.exercise.exercise.name : '';
        return (
          <Pressable
            key={it.key}
            accessibilityRole="button"
            accessibilityState={{ checked: done, selected: isCurrent }}
            onPress={() => (it.kind !== 'practice' ? onEdit(it) : undefined)}
            style={[styles.setRow, isCurrent && styles.setRowCurrent, done && styles.setRowDone]}
          >
            {done ? <Tick size={22} /> : <View style={styles.open} />}
            <Text style={[styles.setText, done && styles.setTextDone]} numberOfLines={1}>
              {[name, label].filter(Boolean).join(' · ') || targetText(it)}
            </Text>
            <Text style={styles.setEntry}>{entryText(player.entryFor(it))}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// --- editing one set ---------------------------------------------------------------------

export function EditSheet({ player, item, onClose }: { player: Player; item: Item | null; onClose: () => void }) {
  const [entry, setEntry] = useState<Entry | null>(null);
  const [forKey, setForKey] = useState<string | null>(null);
  if (item && forKey !== item.key) {
    // A different set was opened: start from its numbers (state reset while drawing,
    // React's recommended way instead of an effect).
    setForKey(item.key);
    setEntry(player.entryFor(item));
  }
  if (!item || !entry) return <Sheet visible={false} onClose={onClose}>{null}</Sheet>;

  const done = player.isDone(item);
  const weighted = player.weighted(item.exercise);
  const showReps = item.kind === 'reps' || item.kind === 'open_reps';
  const showSeconds = item.kind === 'timed' || item.kind === 'open_hold';
  const kgStep = weightStep(player.detail(item.exercise.exercise.id));
  const close = () => {
    setForKey(null);
    onClose();
  };
  const save = () => {
    player.edit(item, entry);
    close();
  };

  return (
    <Sheet visible onClose={close}>
      <Title>{item.exercise.exercise.name}</Title>
      <Body muted>{targetText(item)}</Body>
      {showReps ? (
        <Stepper
          label="Reps"
          unit="reps"
          value={entry.reps}
          onStep={(d) => setEntry({ ...entry, reps: step(entry.reps, d, item.exercise.reps_min ?? 0) })}
          onType={(reps) => setEntry({ ...entry, reps: reps === null ? null : Math.round(reps) })}
        />
      ) : null}
      {weighted ? (
        <Stepper
          label="Weight"
          unit="kg"
          value={entry.weight_kg}
          onStep={(d) => setEntry({ ...entry, weight_kg: step(entry.weight_kg, d * kgStep) })}
          onType={(kg) => setEntry({ ...entry, weight_kg: kg === null ? null : Math.round(kg * 2) / 2 })}
        />
      ) : null}
      {showSeconds ? (
        <Stepper
          label="Seconds"
          unit="s"
          value={entry.seconds}
          onStep={(d) => setEntry({ ...entry, seconds: step(entry.seconds, d * 5) })}
          onType={(s) => setEntry({ ...entry, seconds: s === null ? null : Math.round(s) })}
        />
      ) : null}
      <LockInButton title={done ? 'Save changes' : 'Save'} onPress={save} disabled={!isReady(item, entry)} />
      {done ? (
        <OutlineButton
          title="Untick this set"
          onPress={() => {
            player.untick(item);
            close();
          }}
        />
      ) : null}
      <TextButton title="Cancel" onPress={close} />
    </Sheet>
  );
}

// --- the "More" menu, "How to do it" -------------------------------------------------------

function MoreSheet({
  visible,
  station,
  player,
  onClose,
  onHowTo,
  onFinishNow,
}: {
  visible: boolean;
  station: Station;
  player: Player;
  onClose: () => void;
  onHowTo: (row: PlannedExercise) => void;
  onFinishNow: () => void;
}) {
  const styles = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose}>
      {station.exercises.map((row) => (
        <View key={row.id} style={styles.menuGroup}>
          <Label>{row.exercise.name}</Label>
          <TextButton title="How to do it" onPress={() => onHowTo(row)} />
          {player.online ? (
            <>
              <TextButton
                title="This hurts: swap it"
                onPress={() => {
                  onClose();
                  player.swap(row, 'hurts');
                }}
              />
              <TextButton
                title="Show another (today only)"
                onPress={() => {
                  onClose();
                  player.swap(row, 'another');
                }}
              />
            </>
          ) : (
            <Body muted>Swapping needs a connection. If it hurts, skip it: stop, and skip this exercise.</Body>
          )}
        </View>
      ))}
      <View style={styles.menuGroup}>
        <Label>This workout</Label>
        <TextButton
          title={station.exercises.length > 1 ? 'Skip the rest of this part' : 'Skip this exercise'}
          onPress={() => {
            onClose();
            player.skipStation(station);
          }}
        />
        <TextButton title="Finish workout now" onPress={onFinishNow} />
      </View>
    </Sheet>
  );
}

function HowToSheet({ player, row, onClose }: { player: Player; row: PlannedExercise | null; onClose: () => void }) {
  const detail = row ? player.detail(row.exercise.id) : undefined;
  return (
    <Sheet visible={row !== null} onClose={onClose}>
      <Title>{row?.exercise.name ?? ''}</Title>
      {detail ? (
        <>
          {detail.steps.map((line, index) => (
            <Body key={line}>
              {index + 1}. {line}
            </Body>
          ))}
          {detail.cues.length > 0 ? <Label>Remember</Label> : null}
          {detail.cues.map((cue) => (
            <Body key={cue} muted>
              • {cue}
            </Body>
          ))}
          {detail.common_mistake ? (
            <>
              <Label>Common mistake</Label>
              <Body muted>{detail.common_mistake}</Body>
            </>
          ) : null}
        </>
      ) : (
        <Body muted>Couldn’t load the steps. Check your connection.</Body>
      )}
      <Body muted>{SAFETY_LINE}</Body>
      <TextButton title="Close" onPress={onClose} />
    </Sheet>
  );
}

const AREAS: [BodyArea, string][] = [
  ['knees', 'Knees'],
  ['back', 'Back'],
  ['shoulders', 'Shoulders'],
  ['other', 'Somewhere else'],
];

/** ADR 0020 decision 3: asked once after "this hurts", optional. */
function WhereItHurts({ name, onAnswer }: { name: string; onAnswer: (area: BodyArea | null) => void }) {
  const styles = useStyles();
  return (
    <Card>
      <Label>Where did {name} hurt?</Label>
      <View style={styles.chips}>
        {AREAS.map(([area, label]) => (
          <OutlineButton key={area} title={label} onPress={() => onAnswer(area)} />
        ))}
      </View>
      <TextButton title="Skip" onPress={() => onAnswer(null)} />
    </Card>
  );
}

// --- after the workout -------------------------------------------------------------------

const FEEDBACK = [
  ['too_easy', 'Too easy'],
  ['just_right', 'Just right'],
  ['too_hard', 'Too hard'],
] as const;

export function FeedbackView({ player, onBack }: { player: Player; onBack: (() => void) | null }) {
  const { done, total } = player.totals;
  return (
    <Screen>
      <Label>{player.workout ? `Workout ${player.workout.position}` : 'Workout'}</Label>
      <Title>{finishTitle(done, total)}</Title>
      <Body muted>{finishSubtitle(done, total)}</Body>
      {!player.online ? (
        <Body muted>You’re offline: your workout saves on this phone and syncs when you’re back.</Body>
      ) : null}
      <Label>How did that feel?</Label>
      {FEEDBACK.map(([value, label]) => (
        <Choice
          key={value}
          label={label}
          selected={false}
          onPress={() => (player.finishing ? undefined : player.finish(value))}
        />
      ))}
      <TextButton title="Skip" onPress={() => (player.finishing ? undefined : player.finish(null))} />
      {player.finishing ? <Body muted>Saving your workout…</Body> : null}
      {onBack && !player.finishing ? <TextButton title="‹ Keep going" onPress={onBack} /> : null}
    </Screen>
  );
}

/** Finished, but the results aren't here (yet): offline, or the server's answer was lost
 * on the way (`sent`: the workout itself is saved on the server). */
export function SavedView({
  position,
  sent,
  online,
  onDone,
}: {
  position: number | null;
  sent: boolean;
  online: boolean;
  onDone: () => void;
}) {
  return (
    <Screen footer={<LockInButton title="Lock In: done" onPress={onDone} />}>
      <Label>{position === null ? 'Workout' : `Workout ${position}`} done</Label>
      <Title>Locked in.</Title>
      {sent ? (
        <Body>Your workout is saved.</Body>
      ) : (
        <Card>
          <Label>Saved on this phone</Label>
          <Body>
            {online
              ? 'Sending it now. What moves up next time shows on your plan once it’s there.'
              : 'It syncs when you’re online. Then your plan shows what moves up next time, your XP lands, and your next workout gets ready.'}
          </Body>
        </Card>
      )}
    </Screen>
  );
}

/** The top of the finish screen, revealed one step at a time (ADR 0035): real progress
 * first, then the week, then XP and the level. */
function Headline({ result, bests }: { result: SessionResult; bests: NonNullable<SessionResult['new_bests']> }) {
  const styles = useStyles();
  const kept = keptNowLine(result.week);
  const xp = result.xp ?? null;
  const steps = [];
  if (bests.length > 0) {
    steps.push(
      <FadeIn key="bests">
        <Card style={styles.goldCard}>
          <View style={styles.cardTop}>
            <Trophy />
            <Label>Real progress</Label>
          </View>
          {bests.slice(0, 3).map((best) => (
            <Title key={best.exercise.id}>{newBestLine(best)}</Title>
          ))}
          <Confetti />
        </Card>
      </FadeIn>,
    );
  }
  if (kept) {
    steps.push(
      <FadeIn key="week">
        <Card style={styles.cardRow}>
          <Tick size={40} />
          <View style={styles.grow}>
            <Body>{kept}</Body>
          </View>
        </Card>
      </FadeIn>,
    );
  }
  if (xp?.capped) {
    steps.push(
      <FadeIn key="xp">
        <Body muted>{CAPPED_LINE}</Body>
      </FadeIn>,
    );
  } else if (xp && xp.gained > 0) {
    steps.push(
      <FadeIn key="xp">
        <Card>
          <Label>XP earned</Label>
          <CountUp to={xp.gained} render={(n) => `+${thousands(n)} XP`} />
          {xp.items.map((item) => (
            <Body key={item.source} muted>
              {xpItemLine(item)}
            </Body>
          ))}
        </Card>
      </FadeIn>,
    );
    steps.push(
      <FadeIn key="level">
        <LevelReveal xp={xp} />
      </FadeIn>,
    );
  }
  const shown = useSteps(steps.length);
  return <>{steps.slice(0, shown)}</>;
}

/** A trophy in gold: new bests only. */
function Trophy() {
  const palette = usePalette();
  return (
    <Svg width={26} height={26} viewBox="0 0 24 24" fill="none">
      <Path
        d="M7 4h10v5a5 5 0 0 1-10 0zM7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4M12 14v3M8 20h8"
        stroke={palette.goldText}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

function LevelReveal({ xp }: { xp: NonNullable<SessionResult['xp']> }) {
  const up = xp.after.level > xp.before.level;
  // Once per screen, even if React runs the effect twice (it does while developing).
  const celebrated = useRef(false);
  useEffect(() => {
    if (!up || celebrated.current) return;
    celebrated.current = true;
    celebrate();
  }, [up]);
  return (
    <Card>
      {up ? <Title>{`Lock In level ${xp.after.level}!`}</Title> : null}
      <FillBar from={up ? 0 : levelShare(xp.before)} to={levelShare(xp.after)} />
      <Body muted>{levelLine(xp.after)}</Body>
      {up ? <Confetti /> : null}
    </Card>
  );
}

export function ResultView({
  result,
  position,
  limit,
  onLimit,
  limitSaving,
  onDone,
  synced = false,
}: {
  result: SessionResult;
  position: number | null;
  limit: BodyLimit | null;
  onLimit: (yes: boolean) => void;
  limitSaving: boolean;
  onDone: () => void;
  /** Done offline and sent later: say so. */
  synced?: boolean;
}) {
  const styles = useStyles();
  const up = result.progress.filter(isStepUp);
  const back = result.progress.filter((p) => !isStepUp(p));
  const bests = result.new_bests ?? [];
  return (
    <Screen footer={<LockInButton title="Lock In: done" onPress={onDone} />}>
      <Label>{position === null ? 'Workout' : `Workout ${position}`} done</Label>
      <Title>Locked in.</Title>
      {synced ? <Body muted>Done offline, synced just now.</Body> : null}
      <Headline result={result} bests={bests} />
      <Body muted>
        {result.sets.length} {result.sets.length === 1 ? 'set' : 'sets'} logged.
      </Body>

      {result.placements.length > 0 ? (
        <Card>
          <Label>Your starting points</Label>
          {result.placements.map((p) => (
            <Body key={p.movement}>{placementLine(p)}</Body>
          ))}
        </Card>
      ) : null}

      {up.length > 0 || result.intervals?.direction === 'up' ? (
        <Card>
          <Label>Stepping up</Label>
          {up.map((p) => (
            <Body key={p.exercise.id}>{progressLine(p)}</Body>
          ))}
          {result.intervals?.direction === 'up' ? <Body>{intervalsLine(result.intervals)}</Body> : null}
        </Card>
      ) : null}

      {back.length > 0 || result.intervals?.direction === 'down' ? (
        <Card>
          <Label>Easing off a little</Label>
          {back.map((p) => (
            <Body key={p.exercise.id}>{progressLine(p)}</Body>
          ))}
          {result.intervals?.direction === 'down' ? <Body>{intervalsLine(result.intervals)}</Body> : null}
          <Body muted>That’s how progress works: a step back now, then up again.</Body>
        </Card>
      ) : null}

      {result.recovery_earned ? (
        <Card>
          <Label>Recovery earned</Label>
          <Body>Your lighter week starts now. Rest is part of getting stronger.</Body>
        </Card>
      ) : null}

      {limit ? (
        <Card>
          <Label>One question</Label>
          <Body>{limitQuestion(limit)}</Body>
          <View style={styles.row}>
            <OutlineButton title="Yes" onPress={() => onLimit(true)} disabled={limitSaving} />
            <OutlineButton title="No thanks" onPress={() => onLimit(false)} disabled={limitSaving} />
          </View>
        </Card>
      ) : null}

      {result.block_complete ? (
        <Card>
          <Label>Block complete</Label>
          <Body>Every workout of this block is done. Your next block is ready to start.</Body>
        </Card>
      ) : null}

      {result.offer_reminder ? <ReminderOffer finishedAt={new Date(result.finished_at ?? result.started_at)} /> : null}

      {result.sign_in_offer ? (
        <Card>
          <Label>Your plan knows you</Label>
          {result.sign_in_offer.summary.lines.map((line) => (
            <Body key={line}>{line}</Body>
          ))}
          <Body muted>Signing in with Google or Apple, to keep this safe, comes in the next app update.</Body>
        </Card>
      ) : null}
    </Screen>
  );
}

const useStyles = makeStyles((p) => ({
  grow: { flex: 1 },
  topBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  count: { fontFamily: font.bold, color: p.muted, fontSize: 14 },
  current: { gap: space.s, paddingVertical: space.m, borderColor: p.brand },
  exerciseName: { fontFamily: font.heavy, color: p.text, fontSize: 22 },
  target: { fontFamily: font.heavy, color: p.text, fontSize: 26 },
  entryArea: { gap: space.s, marginTop: space.xs },
  entryHint: { fontFamily: font.bold, color: p.muted, fontSize: 12, letterSpacing: 0.6, textTransform: 'uppercase' },
  boxes: { flexDirection: 'row', gap: 10 },
  box: {
    flex: 1,
    minHeight: 86,
    borderRadius: 16,
    borderWidth: 2,
    borderBottomWidth: 4,
    borderColor: p.edge,
    backgroundColor: p.ground,
    alignItems: 'center',
    justifyContent: 'center',
  },
  boxDown: { borderBottomWidth: 2, marginTop: 2 },
  boxValue: { fontFamily: font.heavy, color: p.text, fontSize: 42, letterSpacing: -1, lineHeight: 46 },
  boxUnit: { fontFamily: font.bold, color: p.muted, fontSize: 13 },
  boxEmpty: { fontFamily: font.bold, color: p.text, fontSize: 18 },
  clock: {
    fontFamily: font.heavy,
    color: p.text,
    fontSize: 64,
    fontVariant: ['tabular-nums'],
    textAlign: 'center',
  },
  rest: { alignItems: 'center', paddingVertical: space.l, backgroundColor: p.chip, borderColor: p.brand },
  row: { flexDirection: 'row', gap: space.m },
  actions: { gap: space.s },
  sets: { gap: 6 },
  setRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 50,
    paddingHorizontal: 14,
    borderRadius: 16,
  },
  setRowCurrent: { backgroundColor: p.card, borderWidth: 2, borderColor: p.edge },
  setRowDone: { backgroundColor: p.chip },
  open: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: p.edge },
  setText: { fontFamily: font.bold, color: p.text, fontSize: 15, flex: 1 },
  setTextDone: { color: p.chipText },
  setEntry: { fontFamily: font.heavy, color: p.text, fontSize: 15 },
  menuGroup: { gap: space.xs },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.s },
  goldCard: { borderColor: p.gold },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: space.s },
  cardRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
}));

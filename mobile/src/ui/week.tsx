/**
 * Home's game pieces and the reminder (ADR 0034, 0035, 0036):
 *
 *   Hud             the Lock In level with its gold XP bar, the streak chip, Settings
 *   WorldCard       where the character lives; it says what's next, never what's lost
 *   WeekTile        "This week" ring: "1 of 3 workouts"
 *   BestsTile       every new best so far
 *   ReminderOffer   on workout 1's finish screen: a reminder with a time already picked
 *   ReminderRows    in Settings: change or turn off the reminder, and a sound check
 *   ReminderSheet   pick the time (half-hour steps) and the days
 *
 * The week is the habit's natural rhythm, so the ring and the streak count weeks: no
 * reason to open the app on a rest day. Gold means rewards only (streak, XP, bests).
 */
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';
import Svg, { Circle, Path, Rect, Text as SvgText } from 'react-native-svg';

import { getBestsTotal, getOrCreatePlan, getWeek, getXp, type Reminder, type Week } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import {
  bubbleLine,
  type ClockTime,
  dayName,
  formatTime,
  freezeLine,
  lastWeekLine,
  parseTime,
  reminderSummary,
  ringLabel,
  stepTime,
  streakLine,
  suggestTime,
} from '@/features/week/words';
import { bestsWord, levelLine, levelParts, levelShare } from '@/features/xp/words';
import { NotificationsOffError, useMe, useSaveReminder } from '@/state/reminders';
import { keys } from '@/state/startup';
import { useSoundCheck } from '@/ui/alerts';
import {
  Body,
  Card,
  Choice,
  Gap,
  IconButton,
  Label,
  LockInButton,
  OutlineButton,
  ProgressBar,
  Row,
  Sheet,
  TextButton,
  Title,
} from '@/ui/kit';
import { chunky, font, makeStyles, type Palette, usePalette } from '@/ui/theme';

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

function toReminder(time: ClockTime, days: number[]): Reminder {
  return { at: `${formatTime(time)}:00`, days: [...days].sort((a, b) => a - b) };
}

function saveError(error: unknown): string {
  return error instanceof NotificationsOffError
    ? 'Notifications are off for Lock In Mode. Turn them on in your phone’s settings, then try again.'
    : describeError(error);
}

// --- the HUD -----------------------------------------------------------------------------

/** Level, XP bar, streak, settings: the game's status line at the top of Home. */
export function Hud() {
  const styles = useStyles();
  const palette = usePalette();
  const xp = useQuery({ queryKey: keys.xp, queryFn: getXp });
  const week = useQuery({ queryKey: keys.week, queryFn: getWeek });
  const [title, amount] = xp.data ? levelParts(xp.data) : ['Lock In level', ''];
  return (
    <View style={styles.hud}>
      <View style={styles.levelBadge}>
        <Text style={styles.levelNumber}>{xp.data?.level ?? '·'}</Text>
      </View>
      <View
        style={styles.grow}
        accessible
        accessibilityLabel={xp.data ? levelLine(xp.data) : 'Lock In level'}
      >
        <View style={styles.hudLine}>
          <Text style={styles.hudTitle}>{title}</Text>
          <Text style={styles.hudAmount}>{amount}</Text>
        </View>
        <ProgressBar value={xp.data ? levelShare(xp.data) : 0} tone="gold" />
      </View>
      <View
        style={styles.streakChip}
        accessible
        accessibilityLabel={`${week.data?.streak ?? 0}-week streak`}
      >
        <Flame palette={palette} />
        <Text style={styles.streakNumber}>{week.data?.streak ?? 0}</Text>
      </View>
      <IconButton label="Settings" onPress={() => router.push('/settings')}>
        <Svg width={20} height={20} viewBox="0 0 24 24" fill="none">
          <Circle cx={12} cy={12} r={3} stroke={palette.muted} strokeWidth={2.2} />
          <Path
            d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"
            stroke={palette.muted}
            strokeWidth={2.2}
            strokeLinecap="round"
          />
        </Svg>
      </IconButton>
    </View>
  );
}

function Flame({ palette, size = 18 }: { palette: Palette; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Path
        d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-7 1 2 2 3 3 4 0-3 0-6 0-9z"
        fill={palette.gold}
        stroke={palette.dark ? '#000000' : palette.outline}
        strokeWidth={1.5}
      />
    </Svg>
  );
}

// --- the world ---------------------------------------------------------------------------

/** The character's place. A placeholder figure until the model sheet is approved; it
 * rests, it never decays (character-bible.md). Speaks the next step; the streak line
 * runs along the bottom. */
export function WorldCard({ waiting = 0 }: { waiting?: number }) {
  const styles = useStyles();
  const palette = usePalette();
  const week = useQuery({ queryKey: keys.week, queryFn: getWeek });
  const shown: Week | undefined = week.data ? { ...week.data, done: week.data.done + waiting } : undefined;
  const w = palette.world;
  const extra = shown ? (freezeLine(shown) ?? lastWeekLine(shown)) : null;
  return (
    <View style={[styles.world, { backgroundColor: w.sky }]}>
      <View style={[styles.sun, { backgroundColor: w.sun }]} />
      <View style={[styles.cloud, { backgroundColor: w.cloud }]} />
      <View style={[styles.cloudSmall, { backgroundColor: w.cloud }]} />
      <View style={[styles.hillBack, { backgroundColor: w.hillBack }]} />
      <View style={[styles.hillLeft, { backgroundColor: w.hill }]} />
      <View style={[styles.hillRight, { backgroundColor: w.hill }]} />
      <View style={styles.figure} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        <Figure />
      </View>
      {shown ? (
        <View style={styles.bubble}>
          <Text style={styles.bubbleText}>{bubbleLine(shown)}</Text>
        </View>
      ) : null}
      {shown ? (
        <View style={styles.strip}>
          <Text style={styles.stripText}>{streakLine(shown)}</Text>
          {extra ? <Text style={styles.stripMuted}>{extra}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

/** The stand-in character: a simple figure in the orange tee (dark outline: the tee and
 * medium skin are too close in greyscale, ui-redesign.md). */
function Figure() {
  return (
    <Svg width={76} height={126} viewBox="0 0 70 120">
      <Path d="M30 6l6-6 3 8z" fill="#2B2118" />
      <Circle cx={35} cy={20} r={14} fill="#B9825F" />
      <Path d="M12 42L0 18M58 42l12-24" stroke="#B9825F" strokeWidth={8} strokeLinecap="round" />
      <Path d="M12 40c0-6 6-8 23-8s23 2 23 8l4 34H8z" fill="#E14705" stroke="#2B2118" strokeWidth={2} />
      <Rect x={13} y={74} width={44} height={34} rx={6} fill="#3A3330" />
      <Rect x={13} y={106} width={20} height={10} rx={4} fill="#FFF6E3" />
      <Rect x={37} y={106} width={20} height={10} rx={4} fill="#FFF6E3" />
      <Circle cx={35} cy={52} r={5} fill="#FFFFFF" />
    </Svg>
  );
}

// --- the tiles ---------------------------------------------------------------------------

const R = 25;
const ROUND = 2 * Math.PI * R;

/** `waiting`: workouts finished on this phone and not sent yet (offline, ADR 0033). */
export function WeekTile({ waiting = 0 }: { waiting?: number }) {
  const styles = useStyles();
  const palette = usePalette();
  const week = useQuery({ queryKey: keys.week, queryFn: getWeek });
  if (!week.data) return <View style={[styles.tile, styles.tileWide]} />;
  const shown = { ...week.data, done: week.data.done + waiting };
  const of = Math.max(shown.planned ?? shown.keep_at, 1);
  const share = Math.min(shown.done / of, 1);
  const label = ringLabel(shown);
  return (
    <View style={[styles.tile, styles.tileWide]}>
      <Svg width={58} height={58} viewBox="0 0 64 64" accessibilityLabel={label}>
        <Circle cx={32} cy={32} r={R} fill="none" stroke={palette.track} strokeWidth={10} />
        {share > 0 ? (
          <Circle
            cx={32}
            cy={32}
            r={R}
            fill="none"
            stroke={palette.brand}
            strokeWidth={10}
            strokeLinecap="round"
            strokeDasharray={`${share * ROUND} ${ROUND}`}
            transform="rotate(-90 32 32)"
          />
        ) : null}
        <SvgText x={32} y={38} textAnchor="middle" fontFamily={font.heavy} fontSize={17} fill={palette.text}>
          {`${shown.done}/${of}`}
        </SvgText>
      </Svg>
      <View style={styles.grow}>
        <Label>This week</Label>
        <Text style={styles.tileLine}>{label}</Text>
      </View>
    </View>
  );
}

export function BestsTile() {
  const styles = useStyles();
  const bests = useQuery({ queryKey: keys.bests, queryFn: getBestsTotal });
  const total = bests.data ?? 0;
  return (
    <View style={[styles.tile, styles.tileSmall]} accessible accessibilityLabel={`${total} ${bestsWord(total)}`}>
      <Text style={styles.tileNumber}>{bests.data === undefined ? '–' : total}</Text>
      <Text style={styles.tileSmallText}>{bestsWord(total)}</Text>
    </View>
  );
}

// --- the reminder ------------------------------------------------------------------------

export function ReminderSheet({
  visible,
  initial,
  onSave,
  onTurnOff,
  onClose,
  saving,
  error,
}: {
  visible: boolean;
  initial: Reminder;
  onSave: (reminder: Reminder) => void;
  onTurnOff?: () => void;
  onClose: () => void;
  saving: boolean;
  error: string | null;
}) {
  const styles = useStyles();
  const [time, setTime] = useState(() => parseTime(initial.at));
  const [days, setDays] = useState<number[]>(initial.days);
  const toggle = (day: number) =>
    setDays((now) => (now.includes(day) ? now.filter((d) => d !== day) : [...now, day]));
  return (
    <Sheet visible={visible} onClose={onClose}>
      <Title>Reminder</Title>
      <Body muted>One reminder on each day you pick. Change it or turn it off any time in Settings.</Body>
      <Gap size="s" />
      <Label>Time</Label>
      <View style={styles.row}>
        <OutlineButton title="−30 min" onPress={() => setTime((t) => stepTime(t, -1))} />
        <Text style={styles.time}>{formatTime(time)}</Text>
        <OutlineButton title="+30 min" onPress={() => setTime((t) => stepTime(t, 1))} />
      </View>
      <Label>Days</Label>
      <View style={styles.wrap}>
        {ALL_DAYS.map((day) => (
          <View key={day} style={styles.day}>
            <Choice label={dayName(day)} selected={days.includes(day)} onPress={() => toggle(day)} multi />
          </View>
        ))}
      </View>
      {error ? <Body>{error}</Body> : null}
      <LockInButton
        title="Save reminder"
        busy={saving}
        disabled={days.length === 0 || saving}
        onPress={() => onSave(toReminder(time, days))}
      />
      {onTurnOff ? <TextButton title="Turn the reminder off" onPress={onTurnOff} /> : null}
      <TextButton title="Cancel" onPress={onClose} />
    </Sheet>
  );
}

/** The plan's training days, as the default days for a reminder. */
function usePlanDays(): number[] {
  const plan = useQuery({ queryKey: keys.plan, queryFn: getOrCreatePlan });
  const days = [...new Set(plan.data?.plan.weekdays ?? [0, 2, 4])].sort((a, b) => a - b);
  return days.length > 0 ? days : [0, 2, 4];
}

/** Workout 1's finish screen (ADR 0034): their training days at the time they just
 * trained, one tap to accept. People who set a reminder stay the longest. */
export function ReminderOffer({ finishedAt }: { finishedAt: Date }) {
  const styles = useStyles();
  const days = usePlanDays();
  const [suggested] = useState(() => toReminder(suggestTime(finishedAt), days));
  const [choice, setChoice] = useState<Reminder | null>(null);
  const [editing, setEditing] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const save = useSaveReminder();
  const reminder = choice ?? suggested;

  if (dismissed) return null;
  if (save.isSuccess) {
    return (
      <Card>
        <Label>Reminder on</Label>
        <Body>{reminderSummary(reminder)}. Change it any time in Settings.</Body>
      </Card>
    );
  }
  return (
    <Card>
      <Label>Make it a habit</Label>
      <Body>Want a reminder on your training days?</Body>
      <Body muted>{reminderSummary(reminder)}</Body>
      {save.error ? <Body>{saveError(save.error)}</Body> : null}
      <View style={styles.row}>
        <OutlineButton title="Remind me" disabled={save.isPending} onPress={() => save.mutate(reminder)} />
        <OutlineButton title="Change" disabled={save.isPending} onPress={() => setEditing(true)} />
      </View>
      <TextButton title="Not now" onPress={() => setDismissed(true)} />
      {editing ? (
        <ReminderSheet
          visible
          initial={reminder}
          saving={save.isPending}
          error={null}
          onClose={() => setEditing(false)}
          onSave={(picked) => {
            setChoice(picked);
            setEditing(false);
            save.mutate(picked);
          }}
        />
      ) : null}
    </Card>
  );
}

/** Settings' reminder rows: the reminder (change or turn off), and the sound check. */
export function ReminderRows() {
  const me = useMe();
  const days = usePlanDays();
  const save = useSaveReminder();
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [openedAt] = useState(() => new Date());
  const current = me.data?.reminder ?? null;

  return (
    <>
      <Row
        title={current ? 'Change the reminder' : 'Set a reminder'}
        value={current ? reminderSummary(current) : 'Off'}
        onPress={() => setEditing(true)}
      />
      <Row title="Sound check" value="Rest beep" onPress={() => setChecking(true)} last />
      {editing ? (
        <ReminderSheet
          visible
          initial={current ?? toReminder(suggestTime(openedAt), days)}
          saving={save.isPending}
          error={save.error ? saveError(save.error) : null}
          onClose={() => setEditing(false)}
          onSave={(reminder) => save.mutate(reminder, { onSuccess: () => setEditing(false) })}
          onTurnOff={current ? () => save.mutate(null, { onSuccess: () => setEditing(false) }) : undefined}
        />
      ) : null}
      {checking ? <SoundCheckSheet onClose={() => setChecking(false)} /> : null}
    </>
  );
}

/** Plays the rest beep now and says whether its sound is ready, to find out why a phone
 * stays quiet (ADR 0034). */
function SoundCheckSheet({ onClose }: { onClose: () => void }) {
  const sound = useSoundCheck();
  const [played, setPlayed] = useState(false);
  return (
    <Sheet visible onClose={onClose}>
      <Title>Sound check</Title>
      <Body>Tap play: you should hear the rest beep and feel a buzz.</Body>
      <Body muted>{sound.loaded ? 'Sound ready.' : 'Getting the sound ready…'}</Body>
      <LockInButton
        title="Play the beep"
        onPress={() => {
          sound.play();
          setPlayed(true);
        }}
      />
      {played ? (
        <Body muted>
          Didn’t hear it? The beep uses the media volume, not the ringer: press volume up while it plays. With
          Bluetooth headphones connected, it plays in them.
        </Body>
      ) : null}
      <TextButton title="Close" onPress={onClose} />
    </Sheet>
  );
}

const useStyles = makeStyles((p) => ({
  grow: { flex: 1 },
  hud: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  levelBadge: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: p.button,
    borderBottomWidth: 4,
    borderBottomColor: p.buttonLip,
    alignItems: 'center',
    justifyContent: 'center',
  },
  levelNumber: { fontFamily: font.heavy, color: p.onButton, fontSize: 18 },
  hudLine: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 5 },
  hudTitle: { fontFamily: font.bold, color: p.text, fontSize: 12 },
  hudAmount: { fontFamily: font.bold, color: p.muted, fontSize: 12 },
  streakChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: p.card,
    borderColor: p.edge,
    borderWidth: 2,
    borderBottomWidth: 4,
    borderRadius: 14,
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  streakNumber: { fontFamily: font.heavy, color: p.text, fontSize: 15 },
  world: {
    height: 256,
    borderRadius: 24,
    overflow: 'hidden',
    borderWidth: 2,
    borderBottomWidth: 5,
    borderColor: p.edge,
  },
  sun: { position: 'absolute', left: 28, top: 26, width: 68, height: 68, borderRadius: 34 },
  cloud: { position: 'absolute', left: 190, top: 44, width: 80, height: 22, borderRadius: 11 },
  cloudSmall: { position: 'absolute', left: 232, top: 32, width: 44, height: 28, borderRadius: 14 },
  hillBack: { position: 'absolute', left: -30, right: -30, bottom: -70, height: 150, borderRadius: 400 },
  hillLeft: { position: 'absolute', left: -60, width: 300, bottom: -92, height: 150, borderRadius: 400 },
  hillRight: { position: 'absolute', right: -60, width: 300, bottom: -102, height: 150, borderRadius: 400 },
  figure: { position: 'absolute', alignSelf: 'center', bottom: 46 },
  bubble: {
    position: 'absolute',
    right: 12,
    top: 14,
    maxWidth: '55%',
    backgroundColor: '#FFF6E3',
    borderColor: '#2B2118',
    borderWidth: 2,
    borderRadius: 14,
    borderBottomRightRadius: 4,
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  bubbleText: { fontFamily: font.bold, color: '#2B2118', fontSize: 13 },
  strip: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(43, 33, 24, 0.82)',
    paddingVertical: 7,
    paddingHorizontal: 12,
  },
  stripText: { fontFamily: font.bold, color: '#FFE9BD', fontSize: 13 },
  stripMuted: { fontFamily: font.regular, color: '#F3D9A4', fontSize: 12, marginTop: 1 },
  tiles: { flexDirection: 'row', gap: 10 },
  tile: {
    ...chunky,
    backgroundColor: p.card,
    borderColor: p.edge,
    borderRadius: 20,
    padding: 12,
    minHeight: 84,
  },
  tileWide: { flex: 1.4, flexDirection: 'row', alignItems: 'center', gap: 10 },
  tileSmall: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  tileLine: { fontFamily: font.bold, color: p.text, fontSize: 15, marginTop: 2 },
  tileNumber: { fontFamily: font.heavy, color: p.goldText, fontSize: 30 },
  tileSmallText: { fontFamily: font.bold, color: p.muted, fontSize: 12, marginTop: 4 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginVertical: 8 },
  time: { fontFamily: font.heavy, color: p.text, fontSize: 30 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 8 },
  day: { minWidth: '30%', flexGrow: 1 },
}));

/** The tiles side by side. */
export function Tiles({ waiting = 0 }: { waiting?: number }) {
  const styles = useStyles();
  return (
    <View style={styles.tiles}>
      <WeekTile waiting={waiting} />
      <BestsTile />
    </View>
  );
}


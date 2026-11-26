/**
 * Home's weekly pieces and the reminder (ADR 0034):
 *
 *   WeekCard        "This week ●●○ 2 of 3 workouts", the streak, freezes
 *   ReminderOffer   on workout 1's finish screen: a reminder with a time already picked
 *   SettingsCard    on Home: change or turn off the reminder, and a sound check
 *   ReminderSheet   pick the time (half-hour steps) and the days
 *
 * The week is the habit's natural rhythm, so the ring and the streak count weeks: no
 * reason to open the app on a rest day. Every line says what's next, never what's lost.
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { getOrCreatePlan, getWeek, getXp, type Reminder } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import {
  type ClockTime,
  dayName,
  formatTime,
  freezeLine,
  lastWeekLine,
  parseTime,
  reminderSummary,
  ringDots,
  ringLabel,
  stepTime,
  streakLine,
  suggestTime,
} from '@/features/week/words';
import { levelLine, levelShare } from '@/features/xp/words';
import { NotificationsOffError, useMe, useSaveReminder } from '@/state/reminders';
import { keys } from '@/state/startup';
import { useSoundCheck } from '@/ui/alerts';
import {
  Body,
  Card,
  Choice,
  colors,
  Gap,
  Label,
  LockInButton,
  OutlineButton,
  ProgressBar,
  Sheet,
  TextButton,
  Title,
} from '@/ui/kit';

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

function toReminder(time: ClockTime, days: number[]): Reminder {
  return { at: `${formatTime(time)}:00`, days: [...days].sort((a, b) => a - b) };
}

function saveError(error: unknown): string {
  return error instanceof NotificationsOffError
    ? 'Notifications are off for Lock In Mode. Turn them on in your phone’s settings, then try again.'
    : describeError(error);
}

// --- the week ------------------------------------------------------------------------------

/** `waiting`: workouts finished on this phone and not sent yet (offline, ADR 0033). */
export function WeekCard({ waiting = 0 }: { waiting?: number }) {
  const week = useQuery({ queryKey: keys.week, queryFn: getWeek });
  if (!week.data) return null;
  const shown = { ...week.data, done: week.data.done + waiting };
  const dots = ringDots(shown.done, shown.planned);
  const extra = freezeLine(week.data) ?? lastWeekLine(week.data);
  return (
    <Card>
      <Label>This week</Label>
      <View style={styles.dots} accessibilityLabel={ringLabel(shown)} accessible>
        {dots.map((filled, i) => (
          <View key={i} style={[styles.dot, filled && styles.dotDone]} />
        ))}
      </View>
      <Body>{ringLabel(shown)}</Body>
      <Body muted>{streakLine(week.data)}</Body>
      {extra ? <Body muted>{extra}</Body> : null}
    </Card>
  );
}

/** "Lock In level 7 · 320 / 1,000 XP" under the week: the second line, never the first. */
export function LevelCard() {
  const xp = useQuery({ queryKey: keys.xp, queryFn: getXp });
  if (!xp.data) return null;
  return (
    <Card>
      <Body muted>{levelLine(xp.data)}</Body>
      <ProgressBar value={levelShare(xp.data)} />
    </Card>
  );
}

// --- the reminder ----------------------------------------------------------------------------

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
  const [time, setTime] = useState(() => parseTime(initial.at));
  const [days, setDays] = useState<number[]>(initial.days);
  const toggle = (day: number) =>
    setDays((now) => (now.includes(day) ? now.filter((d) => d !== day) : [...now, day]));
  return (
    <Sheet visible={visible} onClose={onClose}>
      <Title>Reminder</Title>
      <Body muted>One reminder on each day you pick. Change it or turn it off any time on Home.</Body>
      <Gap size="s" />
      <Label>Time</Label>
      <View style={styles.row}>
        <OutlineButton title="−30 min" onPress={() => setTime((t) => stepTime(t, -1))} />
        <Title>{formatTime(time)}</Title>
        <OutlineButton title="+30 min" onPress={() => setTime((t) => stepTime(t, 1))} />
      </View>
      <Label>Days</Label>
      <View style={styles.wrap}>
        {ALL_DAYS.map((day) => (
          <Choice key={day} label={dayName(day)} selected={days.includes(day)} onPress={() => toggle(day)} multi />
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
        <Body>{reminderSummary(reminder)}. Change it any time on Home.</Body>
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

// --- Home's settings ---------------------------------------------------------------------------

export function SettingsCard() {
  const me = useMe();
  const days = usePlanDays();
  const save = useSaveReminder();
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [openedAt] = useState(() => new Date());
  const current = me.data?.reminder ?? null;

  return (
    <Card>
      <Label>Reminder</Label>
      <Body muted>{current ? reminderSummary(current) : 'Off'}</Body>
      <TextButton title={current ? 'Change the reminder' : 'Set a reminder'} onPress={() => setEditing(true)} />
      <Label>Rest beep</Label>
      <TextButton title="Sound check" onPress={() => setChecking(true)} />
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
    </Card>
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

const styles = StyleSheet.create({
  dots: { flexDirection: 'row', gap: 8, marginVertical: 8 },
  dot: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: colors.text },
  dotDone: { backgroundColor: colors.text },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginVertical: 8 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 8 },
});

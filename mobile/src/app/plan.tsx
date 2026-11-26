/**
 * Your plan (docs/onboarding.md screens 12-13).
 *
 * First visit: the plan doesn't exist yet, so it's built (POST /plans) and its REAL
 * reasons appear one by one ("3 days -> full body", "Knees -> no jumping"): people trust
 * work they can see. Then the week, the choices that only matter to some people
 * (shoulder day, bro split), and one big button for the next workout.
 *
 * The big button opens the next workout ("continue" if it's already open: GET
 * /sessions/current). When the block is done, it starts the next one, after "Ready for
 * more?" if moving up a level is on offer (ADR 0022).
 *
 * Offline (ADR 0033): the plan is the copy saved on the phone, and the next workout is
 * kept ready while online, so it can start anywhere. A workout finished offline waits
 * here ("saved on this phone") until it's sent; then its results show here, and the next
 * workout gets ready. Changing answers and starting a block need a connection.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  getOpenSessionOrNull,
  getOrCreatePlan,
  getProfileOrNull,
  type Plan,
  type ProfileWrite,
  profileWithChanges,
  saveProfile,
  startNextBlock,
  type WorkoutSummary,
} from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { hasProgress, type Journal } from '@/features/offline/journal';
import { groupByWeek, routineLabel, statusLabel } from '@/features/plan/format';
import { useJournal, useJournalStore } from '@/state/journal';
import { useOnline } from '@/state/online';
import { useReadyOffline } from '@/state/ready';
import { useAccountSync, useMe } from '@/state/reminders';
import { keys } from '@/state/startup';
import {
  Body,
  Card,
  Choice,
  colors,
  ErrorView,
  Gap,
  Label,
  Loading,
  LockInButton,
  OutlineButton,
  Screen,
  space,
  TextButton,
  Title,
} from '@/ui/kit';
import { ResultView } from '@/ui/player';
import { SettingsCard, WeekCard } from '@/ui/week';

const REVEAL_STEP_MS = 700;

export default function PlanScreen() {
  const queryClient = useQueryClient();
  const plan = useQuery({ queryKey: keys.plan, queryFn: getOrCreatePlan });
  const online = useOnline();
  const { journal } = useJournal();
  const store = useJournalStore();

  // A workout done offline just arrived: its results first (they'd have shown on the
  // finish screen if the phone had been online).
  if (journal?.done && journal.result) {
    return (
      <ResultView
        result={journal.result}
        position={journal.position}
        limit={null}
        onLimit={() => {}}
        limitSaving={false}
        onDone={store.clear}
        synced
      />
    );
  }
  if (plan.isPending) {
    if (!online) {
      return <ErrorView message="You’re offline. Connect once to get your plan." onRetry={() => plan.refetch()} />;
    }
    return <Loading message="Building your plan…" />;
  }
  if (plan.data === undefined) {
    return <ErrorView message={describeError(plan.error)} onRetry={() => plan.refetch()} />;
  }
  const { plan: current, justCreated } = plan.data;
  if (justCreated) {
    // Seen once: remember it, so the app opening offline doesn't show it again.
    const seen = () => queryClient.setQueryData(keys.plan, { plan: current, justCreated: false });
    return <Reveal reasons={current.reasons} onDone={seen} />;
  }
  return <Week plan={current} />;
}

/** Shows the reasons one at a time, then lets the person continue. */
function Reveal({ reasons, onDone }: { reasons: string[]; onDone: () => void }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    // React: an effect runs after drawing. This one schedules the next line, and the
    // returned function cancels the timer if the screen goes away first.
    if (shown >= reasons.length) return;
    const timer = setTimeout(() => setShown(shown + 1), REVEAL_STEP_MS);
    return () => clearTimeout(timer);
  }, [shown, reasons.length]);
  const done = shown >= reasons.length;

  return (
    <Screen footer={<LockInButton title="Lock In: see my plan" onPress={onDone} disabled={!done} />}>
      <Label>Building your plan</Label>
      <Title>Made for you</Title>
      {reasons.slice(0, shown).map((reason) => (
        <Card key={reason}>
          <Body>{reason}</Body>
        </Card>
      ))}
    </Screen>
  );
}

function Week({ plan }: { plan: Plan }) {
  const next = plan.workouts.find((w) => w.id === plan.next_workout_id);
  const comeback = plan.comeback && !plan.comeback.started ? plan.comeback : null;
  const open = useQuery({ queryKey: keys.openSession, queryFn: getOpenSessionOrNull });
  const nextBlock = useNextBlock();
  const online = useOnline();
  const { journal, syncing } = useJournal();
  const ready = useReadyOffline(next?.id);
  const me = useMe();
  useAccountSync(me.data);

  // The journal (ADR 0033): a workout in progress on this phone, or one finished here
  // and still to be sent. The next workout waits for that one.
  const inProgress = journal && !journal.finish && !journal.lost ? journal : null;
  const sending = journal && journal.finish && !journal.done && !journal.lost ? journal : null;
  const continuing = next !== undefined && open.data?.workout_id === next.id;

  let footer;
  if (inProgress) {
    footer = (
      <LockInButton
        title={`Lock In: continue workout ${inProgress.position}`}
        onPress={() => router.push(`/workout/${inProgress.workoutId}/play`)}
      />
    );
  } else if (sending) {
    footer = (
      <LockInButton
        title={online ? `Syncing workout ${sending.position}…` : 'Connect to get your next workout'}
        disabled
        onPress={() => {}}
      />
    );
  } else if (next && continuing) {
    footer = (
      <LockInButton
        title={`Lock In: continue workout ${next.position}`}
        onPress={() => router.push(`/workout/${next.id}/play`)}
      />
    );
  } else if (next && !online && ready !== 'ready') {
    footer = <LockInButton title={`Connect once to get workout ${next.position} ready`} disabled onPress={() => {}} />;
  } else if (next) {
    footer = (
      <LockInButton
        title={`Lock In: workout ${next.position}`}
        onPress={() => router.push(`/workout/${next.id}`)}
      />
    );
  } else if (plan.block_complete && !plan.level_up) {
    footer = (
      <LockInButton
        title={online ? `Lock In: start block ${plan.block_number + 1}` : `Connect to start block ${plan.block_number + 1}`}
        busy={nextBlock.isPending}
        disabled={!online}
        onPress={() => nextBlock.mutate(false)}
      />
    );
  }

  return (
    <Screen footer={footer}>
      {!online ? <OfflineCard nextPosition={next?.position ?? null} ready={ready === 'ready'} journal={journal} /> : null}
      <JournalCard journal={journal} online={online} syncing={syncing} />
      <WeekCard waiting={sending ? 1 : 0} />

      <Label>
        Block {plan.block_number} · {plan.weeks} weeks
      </Label>
      <Title>{routineLabel(plan.routine_kind)}</Title>

      {comeback ? (
        <Card>
          <Label>Welcome back</Label>
          <Body>
            Your next {comeback.workouts_left} workouts are a little lighter while you settle back
            in.
          </Body>
        </Card>
      ) : null}

      {plan.block_complete ? (
        <Card>
          <Label>Block complete</Label>
          <Body>Every workout of this block is done. Well locked in.</Body>
          {plan.level_up ? <ReadyForMore plan={plan} nextBlock={nextBlock} online={online} /> : null}
          {nextBlock.isError ? <Body>{describeError(nextBlock.error)}</Body> : null}
        </Card>
      ) : null}

      {online ? <Choices plan={plan} /> : null}
      <SettingsCard />

      {groupByWeek(plan.workouts).map((group) => (
        <View key={group.week} style={styles.week}>
          <Label>Week {group.week}</Label>
          {group.workouts.map((workout) => (
            <WorkoutRow key={workout.id} workout={workout} isNext={workout.id === next?.id} />
          ))}
        </View>
      ))}

      <Gap />
      <Label>Why this plan</Label>
      {plan.reasons.map((reason) => (
        <Body key={reason} muted>
          {reason}
        </Body>
      ))}
    </Screen>
  );
}

/** Offline: what still works. */
function OfflineCard({
  nextPosition,
  ready,
  journal,
}: {
  nextPosition: number | null;
  ready: boolean;
  journal: Journal | null;
}) {
  let line = 'Connect once to get your next workout ready.';
  if (journal && !journal.finish && !journal.lost) line = 'Your workout saves on this phone and syncs later.';
  else if (journal?.finish && !journal.done) line = 'Your next workout gets ready once the last one syncs.';
  else if (nextPosition !== null && ready) line = `Workout ${nextPosition} is on this phone, ready to go.`;
  return (
    <Card>
      <Label>Offline</Label>
      <Body>{line}</Body>
    </Card>
  );
}

const LOST: Record<NonNullable<Journal['lost']>, string> = {
  plan_moved: 'Your plan changed while it was on this phone, so it couldn’t be added. The rest of your progress is safe.',
  signed_out: 'Your sign-in ended before it could be sent.',
  gone: 'It was removed from your account before it could be sent.',
};

/** A workout finished on this phone: waiting to be sent, sent without results, or lost. */
function JournalCard({ journal, online, syncing }: { journal: Journal | null; online: boolean; syncing: boolean }) {
  const store = useJournalStore();
  if (!journal) return null;
  if (journal.lost) {
    if (!hasProgress(journal)) return null;
    return (
      <Card>
        <Label>Workout {journal.position} couldn’t be saved</Label>
        <Body>{LOST[journal.lost]}</Body>
        <TextButton title="OK" onPress={store.clear} />
      </Card>
    );
  }
  if (journal.done) {
    // Sent, but the answer with the results was lost on the way (those show otherwise).
    return (
      <Card>
        <Label>Workout {journal.position} is saved</Label>
        <TextButton title="OK" onPress={store.clear} />
      </Card>
    );
  }
  if (!journal.finish) return null;
  return (
    <Card>
      <Label>Workout {journal.position} · saved on this phone</Label>
      <Body>
        {syncing
          ? 'Sending it now…'
          : 'It syncs as soon as you’re online. Then you’ll see what moves up, and your next workout gets ready.'}
      </Body>
      {online && !syncing ? <TextButton title="Try now" onPress={() => void store.sync()} /> : null}
    </Card>
  );
}

function WorkoutRow({ workout, isNext }: { workout: WorkoutSummary; isNext: boolean }) {
  const status = statusLabel(workout.status);
  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => router.push(`/workout/${workout.id}`)}
      style={({ pressed }) => [styles.row, isNext && styles.rowNext, pressed && styles.pressed]}
    >
      <Text style={styles.position}>{workout.position}</Text>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{workout.title}</Text>
        <Text style={styles.rowMeta}>
          {workout.total_minutes} min{workout.recovery ? ' · lighter week' : ''}
          {isNext ? ' · next' : ''}
        </Text>
      </View>
      {status ? <Text style={styles.status}>{status}</Text> : null}
    </Pressable>
  );
}

/** Start the next block; the new plan replaces this one on screen. */
function useNextBlock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (levelUp: boolean) => startNextBlock(levelUp),
    onSuccess: (plan) => {
      queryClient.setQueryData(keys.plan, { plan, justCreated: false });
    },
  });
}

/** "Ready for more?" (ADR 0022): the offer's own lines, yes or not yet. Not yet asks
 * again at the end of the next block. */
function ReadyForMore({
  plan,
  nextBlock,
  online,
}: {
  plan: Plan;
  nextBlock: ReturnType<typeof useNextBlock>;
  online: boolean;
}) {
  const offer = plan.level_up;
  if (!offer) return null;
  return (
    <>
      <Gap size="s" />
      <Label>Ready for more?</Label>
      {offer.what_changes.map((line) => (
        <Body key={line}>{line}</Body>
      ))}
      {offer.check_with_doctor ? (
        <Body muted>Check with a doctor before pushing harder. Your low-intensity limits stay.</Body>
      ) : null}
      {!online ? <Body muted>Connect to start your next block.</Body> : null}
      <LockInButton
        title="Yes, move up"
        busy={nextBlock.isPending && nextBlock.variables === true}
        disabled={nextBlock.isPending || !online}
        onPress={() => nextBlock.mutate(true)}
      />
      <OutlineButton
        title="Not yet"
        disabled={nextBlock.isPending || !online}
        onPress={() => nextBlock.mutate(false)}
      />
    </>
  );
}

/** Choices that only matter to some people (playbook screen 13). Changing one saves the
 * profile; the server rebuilds the untouched plan, still block 1 (ADR 0017). */
function Choices({ plan }: { plan: Plan }) {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: keys.profile, queryFn: getProfileOrNull, staleTime: Infinity });
  const change = useMutation({
    mutationFn: (changes: Partial<ProfileWrite>) => {
      if (!profile.data) throw new Error('No profile loaded');
      return saveProfile(profileWithChanges(profile.data, changes));
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData(keys.profile, saved);
      await queryClient.invalidateQueries({ queryKey: keys.plan });
    },
  });
  const data = profile.data;
  if (!data || (!plan.uses_push_pull_legs && !data.bro_split_available)) return null;

  return (
    <Card>
      {data.bro_split_available ? (
        <>
          <Label>Your split</Label>
          <View style={styles.pair}>
            <View style={styles.half}>
              <Choice
                label="Push pull legs (recommended)"
                selected={!data.prefers_bro_split}
                onPress={() => change.mutate({ prefers_bro_split: false })}
              />
            </View>
            <View style={styles.half}>
              <Choice
                label="Bro split"
                selected={data.prefers_bro_split}
                onPress={() => change.mutate({ prefers_bro_split: true })}
              />
            </View>
          </View>
        </>
      ) : null}
      {plan.uses_push_pull_legs ? (
        <>
          <Label>Shoulders with</Label>
          <View style={styles.pair}>
            <View style={styles.half}>
              <Choice
                label="Push day"
                selected={data.shoulder_day === 'push'}
                onPress={() => change.mutate({ shoulder_day: 'push' })}
              />
            </View>
            <View style={styles.half}>
              <Choice
                label="Leg day"
                selected={data.shoulder_day === 'legs'}
                onPress={() => change.mutate({ shoulder_day: 'legs' })}
              />
            </View>
          </View>
        </>
      ) : null}
      {change.isPending ? <Body muted>Updating your plan…</Body> : null}
      {change.isError ? <Body>{describeError(change.error)}</Body> : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  week: { gap: space.s },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.m,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: space.m,
  },
  rowNext: { borderColor: colors.primary },
  pressed: { opacity: 0.7 },
  position: { color: colors.muted, fontSize: 16, fontWeight: '800', width: 24, textAlign: 'center' },
  rowText: { flex: 1, gap: 2 },
  rowTitle: { color: colors.text, fontSize: 16, fontWeight: '700' },
  rowMeta: { color: colors.muted, fontSize: 14 },
  status: { color: colors.muted, fontSize: 13, fontWeight: '700' },
  pair: { flexDirection: 'row', gap: space.s },
  half: { flex: 1 },
});

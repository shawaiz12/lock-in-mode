/**
 * Your plan (docs/onboarding.md screens 12-13).
 *
 * First visit: the plan doesn't exist yet, so it's built (POST /plans) and its REAL
 * reasons appear one by one ("3 days -> full body", "Knees -> no jumping"): people trust
 * work they can see. Then the week, the choices that only matter to some people
 * (shoulder day, bro split), and one big button for the next workout.
 *
 * The workout player is the next stage; for now the button opens a preview.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  getOrCreatePlan,
  getProfileOrNull,
  type Plan,
  type ProfileWrite,
  profileWithChanges,
  saveProfile,
  type WorkoutSummary,
} from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { groupByWeek, routineLabel, statusLabel } from '@/features/plan/format';
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
  Screen,
  space,
  Title,
} from '@/ui/kit';

const REVEAL_STEP_MS = 700;

export default function PlanScreen() {
  const plan = useQuery({ queryKey: keys.plan, queryFn: getOrCreatePlan });
  const [revealSeen, setRevealSeen] = useState(false);

  if (plan.isPending) return <Loading message="Building your plan…" />;
  if (plan.isError) {
    return <ErrorView message={describeError(plan.error)} onRetry={() => plan.refetch()} />;
  }
  const { plan: current, justCreated } = plan.data;
  if (justCreated && !revealSeen) {
    return <Reveal reasons={current.reasons} onDone={() => setRevealSeen(true)} />;
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

  return (
    <Screen
      footer={
        next ? (
          <LockInButton
            title={`Lock In: workout ${next.position}`}
            onPress={() => router.push(`/workout/${next.id}`)}
          />
        ) : undefined
      }
    >
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
          <Body>Every workout of this block is done. The next block comes with the workout player.</Body>
        </Card>
      ) : null}

      <Choices plan={plan} />

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

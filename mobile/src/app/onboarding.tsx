/**
 * Onboarding (docs/onboarding.md, screens 1-10): one question per screen. Single
 * choices move on by themselves; multi choices and info screens have a "Lock In" button.
 * The answers live in this screen's state until the end, then go to the API in one
 * PUT /me/profile (plus the optional name). Which questions exist and what they become
 * is in src/features/onboarding/flow.ts.
 *
 * React: `useState` is a value that survives redraws (like a field on a MonoBehaviour);
 * setting it redraws the screen. `useMutation` runs a save and tracks busy/error.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import { saveDisplayName, saveProfile } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import {
  type Answers,
  chooseLocation,
  DAYS,
  displayName,
  echoFor,
  EMPTY_ANSWERS,
  EQUIPMENT,
  GOALS,
  HISTORY,
  isAnswered,
  LIMITS,
  LOCATIONS,
  MINUTES,
  OBSTACLES,
  stepsFor,
  toggle,
  toProfileWrite,
} from '@/features/onboarding/flow';
import { keys } from '@/state/startup';
import { Body, Choice, colors, Label, LockInButton, Screen, space, TextButton, Title } from '@/ui/kit';

export default function Onboarding() {
  const [answers, setAnswers] = useState<Answers>(EMPTY_ANSWERS);
  const [index, setIndex] = useState(0);
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: async (final: Answers) => {
      const profile = await saveProfile(toProfileWrite(final));
      const name = displayName(final);
      if (name) await saveDisplayName(name);
      return profile;
    },
    // The new profile moves the app to the safety check (see src/app/_layout.tsx).
    onSuccess: (profile) => queryClient.setQueryData(keys.profile, profile),
  });

  const steps = stepsFor(answers);
  const step = steps[index] ?? 'welcome';

  function next(updated: Answers = answers) {
    if (index >= stepsFor(updated).length - 1) save.mutate(updated);
    else setIndex(index + 1);
  }

  /** One tap on a single-choice answer: remember it and move on. */
  function pick(updated: Answers) {
    setAnswers(updated);
    next(updated);
  }

  const lockIn = (title = 'Lock In') => (
    <LockInButton
      title={save.isError ? 'Try again' : title}
      onPress={() => next()}
      disabled={!isAnswered(step, answers)}
      busy={save.isPending}
    />
  );

  return (
    <Screen
      footer={['welcome', 'echo', 'equipment', 'limits', 'obstacles'].includes(step) ? lockIn() : undefined}
    >
      <View style={styles.topBar}>
        {index > 0 ? <TextButton title="‹ Back" onPress={() => setIndex(index - 1)} /> : <View />}
        <Text style={styles.progress}>
          {index + 1} / {steps.length}
        </Text>
      </View>

      {step === 'welcome' && (
        <>
          <Title>You&apos;re the main character.</Title>
          <Body>Let&apos;s build your plan. About a minute, then your first workout.</Body>
          <TextInput
            style={styles.input}
            placeholder="Your name (optional)"
            placeholderTextColor={colors.muted}
            value={answers.name}
            onChangeText={(name) => setAnswers({ ...answers, name })}
            maxLength={50}
            autoCapitalize="words"
            returnKeyType="done"
            accessibilityLabel="Your name, optional"
          />
        </>
      )}

      {step === 'goal' && (
        <>
          <Title>What&apos;s your goal?</Title>
          {GOALS.map((g) => (
            <Choice
              key={g.value}
              label={g.label}
              selected={answers.goal === g.value}
              onPress={() => pick({ ...answers, goal: g.value })}
            />
          ))}
        </>
      )}

      {step === 'echo' && (
        <>
          <Label>Your plan</Label>
          <Title>{GOALS.find((g) => g.value === answers.goal)?.label}</Title>
          <Body>{echoFor(answers.goal)}</Body>
        </>
      )}

      {step === 'history' && (
        <>
          <Title>How long have you trained steadily?</Title>
          {HISTORY.map((h) => (
            <Choice
              key={h.value}
              label={h.label}
              selected={answers.history === h.value}
              onPress={() => pick({ ...answers, history: h.value })}
            />
          ))}
        </>
      )}

      {step === 'where' && (
        <>
          <Title>Where will you train?</Title>
          {LOCATIONS.map((l) => (
            <Choice
              key={l.value}
              label={l.label}
              selected={answers.location === l.value}
              onPress={() => pick(chooseLocation(answers, l.value))}
            />
          ))}
        </>
      )}

      {step === 'equipment' && (
        <>
          <Title>What do you have at home?</Title>
          <Body muted>Pick any, or none. No equipment is a full plan, not a lesser one.</Body>
          {EQUIPMENT.map((e) => (
            <Choice
              key={e.value}
              multi
              label={e.label}
              selected={answers.equipment.includes(e.value)}
              onPress={() => setAnswers({ ...answers, equipment: toggle(answers.equipment, e.value) })}
            />
          ))}
          <Label>Also</Label>
          <Choice
            multi
            label="Quiet, small-space workouts"
            selected={answers.quiet}
            onPress={() => setAnswers({ ...answers, quiet: !answers.quiet })}
          />
        </>
      )}

      {step === 'days' && (
        <>
          <Title>How many days a week?</Title>
          {DAYS.map((d) => (
            <Choice
              key={d}
              label={`${d} days`}
              selected={answers.days === d}
              onPress={() => pick({ ...answers, days: d })}
            />
          ))}
        </>
      )}

      {step === 'time' && (
        <>
          <Title>How long per workout?</Title>
          <Body muted>10 minutes counts.</Body>
          {MINUTES.map((m) => (
            <Choice
              key={m.label}
              label={m.label}
              selected={answers.minutes === m.value}
              onPress={() => pick({ ...answers, minutes: m.value })}
            />
          ))}
        </>
      )}

      {step === 'limits' && (
        <>
          <Title>Anything to train around?</Title>
          <Body muted>We train around a sore area. We don&apos;t treat it.</Body>
          {LIMITS.map((l) => (
            <Choice
              key={l.value}
              multi
              label={l.label}
              selected={answers.limits.includes(l.value)}
              onPress={() => setAnswers({ ...answers, limits: toggle(answers.limits, l.value) })}
            />
          ))}
          <Choice
            label="None"
            selected={answers.limits.length === 0}
            onPress={() => setAnswers({ ...answers, limits: [] })}
          />
        </>
      )}

      {step === 'obstacles' && (
        <>
          <Title>What&apos;s made it hard before?</Title>
          <Body muted>Optional. It changes your tips and reminders, not your plan.</Body>
          {OBSTACLES.map((o) => (
            <Choice
              key={o.value}
              multi
              label={o.label}
              selected={answers.obstacles.includes(o.value)}
              onPress={() =>
                setAnswers({ ...answers, obstacles: toggle(answers.obstacles, o.value) })
              }
            />
          ))}
          {answers.obstacles.length === 0 && !save.isPending ? (
            <TextButton title="Skip" onPress={() => next()} />
          ) : null}
        </>
      )}

      {save.isError ? <Body>{describeError(save.error)}</Body> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    minHeight: 40,
  },
  progress: { color: colors.muted, fontSize: 14, fontWeight: '600' },
  input: {
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: 14,
    color: colors.text,
    fontSize: 17,
    paddingVertical: 16,
    paddingHorizontal: space.m,
  },
});

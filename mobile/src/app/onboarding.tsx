/**
 * Onboarding (docs/onboarding.md, ADR 0036): six questions, one per screen, steps 1-6 of
 * the 8-step first run (then the safety list and the pact). Single choices move on by
 * themselves; home kit and sore spots have a "Lock In" button. Every screen says why it
 * asks. The answers live in this screen's state until the end, then go to the API in one
 * PUT /me/profile. Which questions exist and what they become is in
 * src/features/onboarding/flow.ts.
 *
 * React: `useState` is a value that survives redraws (like a field on a MonoBehaviour);
 * setting it redraws the screen. `useMutation` runs a save and tracks busy/error.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { saveProfile } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import {
  type Answers,
  chooseLocation,
  DAY_HINTS,
  DAYS,
  EMPTY_ANSWERS,
  EQUIPMENT,
  echoFor,
  FLOW_LENGTH,
  GOALS,
  HISTORY,
  isAnswered,
  LIMITS,
  LOCATIONS,
  MINUTES,
  needsButton,
  QUESTIONS,
  STEPS,
  toggle,
  toProfileWrite,
} from '@/features/onboarding/flow';
import { keys } from '@/state/startup';
import { Body, Card, Choice, Label, LockInButton, Screen, StepHeader, Tick, Title } from '@/ui/kit';
import { makeStyles, space } from '@/ui/theme';

export default function Onboarding() {
  const styles = useStyles();
  const [answers, setAnswers] = useState<Answers>(EMPTY_ANSWERS);
  const [index, setIndex] = useState(0);
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: (final: Answers) => saveProfile(toProfileWrite(final)),
    // The new profile moves the app to the safety check (see src/app/_layout.tsx).
    onSuccess: (profile) => queryClient.setQueryData(keys.profile, profile),
  });

  const step = STEPS[index] ?? 'goal';
  const question = QUESTIONS[step];

  function next(updated: Answers = answers) {
    if (index >= STEPS.length - 1) save.mutate(updated);
    else setIndex(index + 1);
  }

  /** One tap on a single-choice answer: remember it and move on. */
  function pick(updated: Answers) {
    setAnswers(updated);
    next(updated);
  }

  const footer = needsButton(step, answers) ? (
    <LockInButton
      title={save.isError ? 'Try again' : 'Lock In'}
      onPress={() => next()}
      disabled={!isAnswered(step, answers)}
      busy={save.isPending}
    />
  ) : undefined;

  return (
    <Screen
      header={
        <StepHeader
          step={index + 1}
          of={FLOW_LENGTH}
          onBack={index > 0 && !save.isPending ? () => setIndex(index - 1) : undefined}
        />
      }
      footer={footer}
    >
      {step === 'goal' ? <Label>Let’s build your plan</Label> : null}
      {step === 'history' && answers.goal ? (
        // The goal's echo: proof we listened, without a screen of its own.
        <Card style={styles.echo}>
          <Tick size={22} />
          <View style={styles.grow}>
            <Body>{echoFor(answers.goal)}</Body>
          </View>
        </Card>
      ) : null}
      <Title>{question.title}</Title>
      <Body muted>{question.why}</Body>

      {step === 'goal' &&
        GOALS.map((g) => (
          <Choice
            key={g.value}
            label={g.label}
            hint={g.hint}
            selected={answers.goal === g.value}
            onPress={() => pick({ ...answers, goal: g.value })}
          />
        ))}

      {step === 'history' &&
        HISTORY.map((h) => (
          <Choice
            key={h.value}
            label={h.label}
            hint={h.hint}
            selected={answers.history === h.value}
            onPress={() => pick({ ...answers, history: h.value })}
          />
        ))}

      {step === 'where' && (
        <>
          {LOCATIONS.map((l) => (
            <Choice
              key={l.value}
              label={l.label}
              hint={l.hint}
              selected={answers.location === l.value}
              onPress={() => {
                const updated = chooseLocation(answers, l.value);
                // The gym has everything: move on. Home asks what's there first.
                if (l.value === 'gym') pick(updated);
                else setAnswers(updated);
              }}
            />
          ))}
          {answers.location === 'home' ? (
            <>
              <Label>What do you have at home?</Label>
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
              <Choice
                multi
                label="Quiet, small-space workouts"
                selected={answers.quiet}
                onPress={() => setAnswers({ ...answers, quiet: !answers.quiet })}
              />
            </>
          ) : null}
        </>
      )}

      {step === 'days' &&
        DAYS.map((d) => (
          <Choice
            key={d}
            badge={String(d)}
            label={`${d} days`}
            hint={DAY_HINTS[d]}
            selected={answers.days === d}
            onPress={() => pick({ ...answers, days: d })}
          />
        ))}

      {step === 'time' &&
        MINUTES.map((m) => (
          <Choice
            key={m.label}
            label={m.label}
            selected={answers.minutes === m.value}
            onPress={() => pick({ ...answers, minutes: m.value })}
          />
        ))}

      {step === 'limits' && (
        <>
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
            selected={false}
            onPress={() => (save.isPending ? undefined : pick({ ...answers, limits: [] }))}
          />
        </>
      )}

      {save.isPending && !footer ? <Body muted>Saving your answers…</Body> : null}
      {save.isError ? <Body>{describeError(save.error)}</Body> : null}
    </Screen>
  );
}

const useStyles = makeStyles(() => ({
  echo: { flexDirection: 'row', alignItems: 'flex-start', gap: space.s + 4 },
  grow: { flex: 1 },
}));

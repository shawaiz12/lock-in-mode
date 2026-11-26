/**
 * Quick safety check (docs/onboarding.md, ADR 0012), step 7 of 8: the four questions as
 * one list since ADR 0036. "None of these" is one tap; ticking any shows the doctor note
 * and a "Lock In" button. Required before the first plan. The server keeps only the
 * result ("keep things gentle"), never the answers.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { submitSafetyScreen } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { FLOW_LENGTH, SAFETY_STEP, toggle } from '@/features/onboarding/flow';
import { QUESTIONS, type SafetyKey, screenFrom } from '@/features/safety/answers';
import { keys } from '@/state/startup';
import { Body, Card, Choice, Label, LockInButton, Screen, StepHeader, Title } from '@/ui/kit';

export default function Safety() {
  const [ticked, setTicked] = useState<SafetyKey[]>([]);
  const queryClient = useQueryClient();
  const submit = useMutation({
    mutationFn: submitSafetyScreen,
    // safety_screened_at is now set, so the app moves on (the pact, or the plan).
    onSuccess: (profile) => queryClient.setQueryData(keys.profile, profile),
  });
  const send = (yes: SafetyKey[]) => (submit.isPending ? undefined : submit.mutate(screenFrom(yes)));

  return (
    <Screen
      header={<StepHeader step={SAFETY_STEP} of={FLOW_LENGTH} />}
      footer={
        ticked.length > 0 ? (
          <LockInButton
            title={submit.isError ? 'Try again' : 'Lock In'}
            onPress={() => send(ticked)}
            busy={submit.isPending}
          />
        ) : undefined
      }
    >
      <Title>Quick safety check</Title>
      <Body muted>Tick any that apply to you. We keep only the result, never your answers.</Body>
      {QUESTIONS.map((q) => (
        <Choice
          key={q.key}
          multi
          label={q.item}
          selected={ticked.includes(q.key)}
          onPress={() => setTicked(toggle(ticked, q.key))}
        />
      ))}
      {ticked.length === 0 ? (
        <Choice label="None of these" selected={false} onPress={() => send([])} />
      ) : (
        <Card>
          <Label>Please read</Label>
          <Body>Please check with a doctor first. We’ll keep things gentle.</Body>
        </Card>
      )}
      {submit.isPending && ticked.length === 0 ? <Body muted>Saving…</Body> : null}
      {submit.isError ? <Body>{describeError(submit.error)}</Body> : null}
    </Screen>
  );
}

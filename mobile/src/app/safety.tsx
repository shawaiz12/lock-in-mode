/**
 * Quick safety check (docs/onboarding.md screen 11, ADR 0012): four yes/no questions,
 * required before the first plan. The server keeps only the result ("keep things
 * gentle"), never the answers. Any "yes": we say so plainly and keep the plan gentle.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { submitSafetyScreen } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { anyYes, completeAnswers, QUESTIONS, type SafetyAnswers } from '@/features/safety/answers';
import { keys } from '@/state/startup';
import { Body, Card, Choice, colors, Label, LockInButton, Screen, space, Title } from '@/ui/kit';

export default function Safety() {
  const [answers, setAnswers] = useState<SafetyAnswers>({});
  const queryClient = useQueryClient();
  const submit = useMutation({
    mutationFn: submitSafetyScreen,
    // safety_screened_at is now set, so the app moves on to the plan.
    onSuccess: (profile) => queryClient.setQueryData(keys.profile, profile),
  });
  const body = completeAnswers(answers);
  const showDoctorNote = anyYes(answers);

  return (
    <Screen
      footer={
        <LockInButton
          title={submit.isError ? 'Try again' : 'Lock In'}
          onPress={() => body && submit.mutate(body)}
          disabled={!body}
          busy={submit.isPending}
        />
      }
    >
      <Title>Quick safety check</Title>
      <Body muted>Four yes or no questions. We keep only the result, never your answers.</Body>
      {QUESTIONS.map((q) => (
        <View key={q.key} style={styles.question}>
          <Body>{q.text}</Body>
          <View style={styles.row} accessibilityRole="radiogroup">
            <View style={styles.half}>
              <Choice
                label="Yes"
                selected={answers[q.key] === true}
                onPress={() => setAnswers({ ...answers, [q.key]: true })}
              />
            </View>
            <View style={styles.half}>
              <Choice
                label="No"
                selected={answers[q.key] === false}
                onPress={() => setAnswers({ ...answers, [q.key]: false })}
              />
            </View>
          </View>
        </View>
      ))}
      {showDoctorNote ? (
        <Card style={styles.warning}>
          <Label>Please read</Label>
          <Body>Please check with a doctor first. We&apos;ll keep things gentle.</Body>
        </Card>
      ) : null}
      {submit.isError ? <Body>{describeError(submit.error)}</Body> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  question: { gap: space.s },
  row: { flexDirection: 'row', gap: space.s },
  half: { flex: 1 },
  warning: { borderColor: colors.warning },
});

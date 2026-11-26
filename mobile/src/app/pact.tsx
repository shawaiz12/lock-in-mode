/**
 * The Lock In pact (ADR 0036), step 8 of 8 and the last screen before the plan: the
 * person's own promise, written from their answers, signed with a finger. Signing stamps
 * it "LOCKED IN" with confetti and one buzz, then the plan opens.
 *
 * - The drawing is only for the moment: it's never sent or saved. The server keeps the
 *   date (`POST /me/pact`).
 * - It's shown only before the first plan (`pact_due`), so nobody who already trains
 *   is ever sent here.
 * - Screen readers can't draw: "Sign here" is also a button that signs for them.
 *
 * No scrolling here on purpose: a scroll view would steal the finger while signing.
 * .NET/Unity: the pad is like an IPointerDragHandler adding points to a LineRenderer.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type Dispatch, type SetStateAction, useEffect, useState } from 'react';
import { Animated, Easing, type GestureResponderEvent, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { getProfileOrNull, type Profile, signPact } from '@/api/endpoints';
import { describeError } from '@/api/problem';
import { FLOW_LENGTH, PACT_STEP } from '@/features/onboarding/flow';
import {
  isSigned,
  pactDate,
  pactFacts,
  type Point,
  promiseLines,
  strokePath,
} from '@/features/pact/words';
import { keys } from '@/state/startup';
import { Body, LockInButton, StepHeader, TextButton, Title } from '@/ui/kit';
import { celebrate, Confetti, useReduceMotion } from '@/ui/reveal';
import { font, makeStyles, PAPER, space } from '@/ui/theme';

/** How long the stamp is shown before the plan opens. */
export const STAMP_MS = 1400;

export default function Pact() {
  const styles = useStyles();
  const queryClient = useQueryClient();
  const reduce = useReduceMotion();
  const profile = useQuery({ queryKey: keys.profile, queryFn: getProfileOrNull, staleTime: Infinity });
  const [strokes, setStrokes] = useState<Point[][]>([]);
  const [signed, setSigned] = useState<Profile | null>(null);
  const [today] = useState(() => new Date());

  const sign = useMutation({
    mutationFn: signPact,
    onSuccess: (saved) => {
      setSigned(saved);
      celebrate();
    },
  });

  // After the stamp has landed, the saved profile moves the app on to the plan.
  useEffect(() => {
    if (!signed) return;
    const timer = setTimeout(() => queryClient.setQueryData(keys.profile, signed), reduce ? 600 : STAMP_MS);
    return () => clearTimeout(timer);
  }, [signed, reduce, queryClient]);

  const data = profile.data;
  if (!data) return null;
  const [promise, comeback] = promiseLines(data);
  const ready = isSigned(strokes);

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <View style={styles.body}>
        <StepHeader step={PACT_STEP} of={FLOW_LENGTH} />
        <Title>Sign your pact</Title>
        <Body muted>A promise to yourself. Small enough to keep.</Body>

        <View style={styles.card}>
          <View style={styles.cardTop}>
            <Text style={styles.brand}>LOCK IN MODE</Text>
            <Text style={styles.date}>{pactDate(today)}</Text>
          </View>
          <View style={styles.rule} />
          <Text style={styles.small}>MY PACT</Text>
          <Text style={styles.promise}>{promise}</Text>
          <Text style={styles.promise}>{comeback}</Text>
          <View style={styles.facts}>
            {pactFacts(data).map((fact) => (
              <View key={fact.label} style={styles.fact}>
                <Text style={styles.factValue}>{fact.value}</Text>
                <Text style={styles.factLabel}>{fact.label}</Text>
              </View>
            ))}
          </View>
          <View style={styles.rule} />
          <SignaturePad strokes={strokes} onChange={setStrokes} locked={signed !== null || sign.isPending} />
          {signed ? <Stamp /> : null}
        </View>
        {strokes.length > 0 && !signed && !sign.isPending ? (
          <TextButton title="Clear and sign again" onPress={() => setStrokes([])} />
        ) : null}
        {sign.isError ? <Body>{describeError(sign.error)}</Body> : null}
      </View>
      <View style={styles.footer}>
        {signed ? <Confetti /> : null}
        {signed ? (
          // Not greyed out: this is the moment it worked, the plan opens next.
          <LockInButton title="Locked in!" onPress={() => {}} />
        ) : (
          <LockInButton
            title={sign.isError ? 'Try again' : 'I’m locked in'}
            onPress={() => sign.mutate()}
            disabled={!ready}
            busy={sign.isPending}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

/** Draw with a finger. Each touch-down starts a stroke; moving adds points. Uses the
 * View's own touch "responder" props (React Native's gesture system at its simplest). */
function SignaturePad({
  strokes,
  onChange,
  locked,
}: {
  strokes: Point[][];
  onChange: Dispatch<SetStateAction<Point[][]>>;
  locked: boolean;
}) {
  const styles = useStyles();
  const at = (event: GestureResponderEvent): Point => ({
    x: event.nativeEvent.locationX,
    y: event.nativeEvent.locationY,
  });
  return (
    <View
      style={styles.pad}
      accessible
      accessibilityRole="button"
      accessibilityLabel="Sign here"
      accessibilityHint="Draw your signature with a finger, or activate to sign"
      accessibilityActions={[{ name: 'activate' }]}
      onAccessibilityAction={() => {
        if (!locked) onChange([SIGN_FOR_THEM]);
      }}
      onStartShouldSetResponder={() => !locked}
      onMoveShouldSetResponder={() => !locked}
      onResponderTerminationRequest={() => false}
      onResponderGrant={(event) => {
        const point = at(event);
        onChange((all) => [...all, [point]]);
      }}
      onResponderMove={(event) => {
        const point = at(event);
        onChange((all) => [...all.slice(0, -1), [...(all[all.length - 1] ?? []), point]]);
      }}
    >
      <Svg style={styles.ink} pointerEvents="none">
        {strokes.map((stroke, i) => (
          <Path
            key={i}
            d={strokePath(stroke)}
            stroke={PAPER.ink}
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        ))}
      </Svg>
      <View style={styles.line} pointerEvents="none" />
      <Text style={styles.small} pointerEvents="none">
        {strokes.length === 0 ? 'SIGN HERE WITH YOUR FINGER' : 'SIGNED'}
      </Text>
    </View>
  );
}

/** A simple flourish, for people who sign without drawing (screen readers). */
const SIGN_FOR_THEM: Point[] = Array.from({ length: 12 }, (_, i) => ({
  x: 10 + i * 12,
  y: 30 + Math.sin(i / 1.5) * 10,
}));

/** "LOCKED IN": thumps down from big to its place. Still, with reduce motion. */
function Stamp() {
  const styles = useStyles();
  const reduce = useReduceMotion();
  const [land] = useState(() => new Animated.Value(reduce ? 1 : 0));
  useEffect(() => {
    if (reduce) return;
    Animated.timing(land, {
      toValue: 1,
      duration: 260,
      easing: Easing.in(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [land, reduce]);
  const scale = land.interpolate({ inputRange: [0, 1], outputRange: [2.2, 1] });
  return (
    <Animated.View
      style={[styles.stamp, { opacity: land, transform: [{ rotate: '-14deg' }, { scale }] }]}
      accessibilityRole="text"
      accessibilityLabel="Locked in, starting today"
    >
      <Text style={styles.stampBig}>LOCKED IN</Text>
      <Text style={styles.stampSmall}>STARTING TODAY</Text>
    </Animated.View>
  );
}

const useStyles = makeStyles((p) => ({
  screen: { flex: 1, backgroundColor: p.ground },
  body: { flex: 1, padding: space.m, gap: 12 },
  footer: { paddingHorizontal: space.m, paddingBottom: space.m, alignItems: 'stretch' },
  card: {
    backgroundColor: PAPER.paper,
    borderColor: PAPER.ink,
    borderWidth: 2,
    borderBottomWidth: 6,
    borderRadius: 20,
    padding: 18,
    gap: 6,
    transform: [{ rotate: '-1.2deg' }],
    marginTop: space.s,
  },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  brand: { fontFamily: font.heavy, color: PAPER.ink, fontSize: 20, letterSpacing: -0.3 },
  date: { fontFamily: font.bold, color: PAPER.faint, fontSize: 12 },
  rule: { borderTopWidth: 2, borderStyle: 'dashed', borderColor: PAPER.rule, marginVertical: 8 },
  small: { fontFamily: font.bold, color: PAPER.faint, fontSize: 11, letterSpacing: 1 },
  promise: { fontFamily: font.bold, color: PAPER.ink, fontSize: 19, lineHeight: 26 },
  facts: { flexDirection: 'row', gap: space.s, marginTop: 10 },
  fact: { flex: 1 },
  factValue: { fontFamily: font.heavy, color: PAPER.ink, fontSize: 14 },
  factLabel: { fontFamily: font.regular, color: PAPER.faint, fontSize: 12 },
  pad: { height: 96, justifyContent: 'flex-end' },
  ink: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 },
  line: { borderTopWidth: 2, borderColor: PAPER.ink, marginBottom: 4 },
  stamp: {
    position: 'absolute',
    right: 14,
    bottom: 48,
    borderWidth: 3,
    borderColor: p.brand,
    backgroundColor: PAPER.paper,
    borderRadius: 10,
    paddingVertical: 4,
    paddingHorizontal: 10,
    alignItems: 'center',
  },
  stampBig: { fontFamily: font.heavy, color: PAPER.stamp, fontSize: 18, letterSpacing: 1 },
  stampSmall: { fontFamily: font.heavy, color: PAPER.stamp, fontSize: 10, letterSpacing: 1 },
}));

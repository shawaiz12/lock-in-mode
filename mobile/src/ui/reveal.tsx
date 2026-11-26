/**
 * The finish screen's reveal (ADR 0035): one thing at a time, so each win gets its own
 * moment. New bests → "This week counts" → XP counting up → the level bar filling →
 * level-up. "Juice": movement and timing make a reward feel bigger without changing it.
 *
 * - React Native's own Animated (no package): opacity and movement run on the native
 *   side (`useNativeDriver`), smooth on cheap Android phones.
 * - The phone's "reduce motion" setting shows everything at once, still.
 * - Confetti (his choice) only for level-ups, new bests and the pact, so it stays
 *   special: a short burst of orange and gold squares.
 * .NET/Unity: like a coroutine revealing UI elements with DOTween easing.
 */
import * as Haptics from 'expo-haptics';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Text, View } from 'react-native';

import { getFeel } from '@/state/feel';
import { font, makeStyles } from '@/ui/theme';

export const STEP_MS = 450;

/** true when the phone asks for less motion. */
export function useReduceMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((on) => alive && setReduce(on))
      .catch(() => {});
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduce);
    return () => {
      alive = false;
      sub.remove();
    };
  }, []);
  return reduce;
}

/** How many of `count` steps to show: the first at once, then one every STEP_MS. */
export function useSteps(count: number): number {
  const reduce = useReduceMotion();
  const [shown, setShown] = useState(1);
  useEffect(() => {
    if (shown >= count) return;
    const timer = setTimeout(() => setShown((n) => n + 1), STEP_MS);
    return () => clearTimeout(timer);
  }, [shown, count]);
  return reduce ? count : Math.min(shown, count);
}

/** Fades and slides in when it first appears. */
export function FadeIn({ children }: { children: ReactNode }) {
  const reduce = useReduceMotion();
  const [progress] = useState(() => new Animated.Value(0));
  useEffect(() => {
    Animated.timing(progress, {
      toValue: 1,
      duration: 300,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [progress]);
  if (reduce) return <View>{children}</View>;
  const translateY = progress.interpolate({ inputRange: [0, 1], outputRange: [12, 0] });
  return <Animated.View style={{ opacity: progress, transform: [{ translateY }] }}>{children}</Animated.View>;
}

/** A number counting up to `to`, eased. Shows the final text at once with reduce motion. */
export function CountUp({ to, render, style }: { to: number; render: (n: number) => string; style?: object }) {
  const styles = useStyles();
  const reduce = useReduceMotion();
  const [value, setValue] = useState(0);
  const [anim] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (reduce) return;
    const id = anim.addListener(({ value: v }) => setValue(Math.round(v)));
    Animated.timing(anim, { toValue: to, duration: 700, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start(
      () => setValue(to),
    );
    return () => anim.removeListener(id);
  }, [anim, to, reduce]);
  return <Text style={[styles.count, style]}>{render(reduce ? to : value)}</Text>;
}

/** The level bar filling from `from` to `to` (0..1). */
export function FillBar({ from, to }: { from: number; to: number }) {
  const styles = useStyles();
  const reduce = useReduceMotion();
  const [fill] = useState(() => new Animated.Value(from));
  useEffect(() => {
    if (reduce) {
      fill.setValue(to);
      return;
    }
    Animated.timing(fill, { toValue: to, duration: 700, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
  }, [fill, to, reduce]);
  const width = fill.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });
  return (
    <View style={styles.track} accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: Math.round(to * 100) }}>
      <Animated.View style={[styles.fill, { width }]} />
    </View>
  );
}

const PIECES = 16;

/** A short burst of plain squares, once. Nothing with reduce motion. */
export function Confetti() {
  const styles = useStyles();
  const reduce = useReduceMotion();
  const [burst] = useState(() => new Animated.Value(0));
  const fired = useRef(false);
  useEffect(() => {
    if (reduce || fired.current) return;
    fired.current = true;
    Animated.timing(burst, { toValue: 1, duration: 900, easing: Easing.out(Easing.quad), useNativeDriver: true }).start();
  }, [burst, reduce]);
  if (reduce) return null;
  return (
    <View pointerEvents="none" style={styles.confetti} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {Array.from({ length: PIECES }, (_, i) => {
        const angle = (i / PIECES) * Math.PI * 2;
        const distance = 60 + (i % 4) * 18;
        const x = burst.interpolate({ inputRange: [0, 1], outputRange: [0, Math.cos(angle) * distance] });
        const y = burst.interpolate({ inputRange: [0, 1], outputRange: [0, Math.sin(angle) * distance + 30] });
        const opacity = burst.interpolate({ inputRange: [0, 0.7, 1], outputRange: [1, 1, 0] });
        const rotate = burst.interpolate({ inputRange: [0, 1], outputRange: ['0deg', `${(i % 2 ? 1 : -1) * 180}deg`] });
        return (
          <Animated.View
            key={i}
            style={[styles.piece, i % 3 === 0 && styles.pieceMuted, { opacity, transform: [{ translateX: x }, { translateY: y }, { rotate }] }]}
          />
        );
      })}
    </View>
  );
}

/** A firm "well done" buzz for the biggest moments (unless vibration is off in
 * Settings). Never breaks anything. */
export function celebrate(): void {
  if (!getFeel().vibration) return;
  try {
    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  } catch {
    // no haptics on this phone
  }
}

const useStyles = makeStyles((p) => ({
  count: { fontFamily: font.heavy, color: p.goldText, fontSize: 34 },
  track: {
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: p.outline,
    backgroundColor: p.track,
    overflow: 'hidden',
    marginVertical: 8,
  },
  fill: { height: '100%', backgroundColor: p.gold },
  confetti: { position: 'absolute', top: 0, left: '50%', width: 0, height: 0 },
  piece: { position: 'absolute', width: 9, height: 9, backgroundColor: p.brand },
  pieceMuted: { backgroundColor: p.gold },
}));

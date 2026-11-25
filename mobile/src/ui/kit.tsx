/**
 * The app's few building blocks, in the brand's black and white. Screens combine these
 * instead of styling from scratch, so every screen looks and behaves the same.
 * .NET/Unity: like a set of prefabs (or Blazor components) with fixed styles.
 *
 * React basics in one place: a component is a function that returns what to draw
 * (JSX). `props` are its inputs (like constructor parameters). It redraws when its
 * props or its state change.
 */
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export const colors = {
  background: '#000000',
  surface: '#111111',
  border: '#2A2A2A',
  text: '#FFFFFF',
  muted: '#9A9A9A',
  primary: '#FFFFFF',
  onPrimary: '#000000',
  warning: '#FFD166',
};

export const space = { xs: 4, s: 8, m: 16, l: 24, xl: 32 };

/** A full screen: safe from notches, scrollable body, optional fixed bottom area
 * (the big "Lock In" button lives there, always in reach of a thumb). */
export function Screen({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {children}
      </ScrollView>
      {footer ? <View style={styles.footer}>{footer}</View> : null}
    </SafeAreaView>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return (
    <Text style={styles.title} accessibilityRole="header">
      {children}
    </Text>
  );
}

export function Body({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return <Text style={[styles.body_text, muted && styles.muted]}>{children}</Text>;
}

export function Label({ children }: { children: ReactNode }) {
  return <Text style={styles.label}>{children}</Text>;
}

/** The main action of a screen. Its words say what happens ("Lock In", not "Next"). */
export function LockInButton({
  title,
  onPress,
  disabled,
  busy,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const off = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: off, busy }}
      onPress={onPress}
      disabled={off}
      style={({ pressed }) => [styles.primary, off && styles.off, pressed && styles.pressed]}
    >
      {busy ? (
        <ActivityIndicator color={colors.onPrimary} />
      ) : (
        <Text style={styles.primaryText}>{title}</Text>
      )}
    </Pressable>
  );
}

/** A quieter button: back, skip, small choices. */
export function TextButton({ title, onPress }: { title: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} hitSlop={12}>
      {({ pressed }) => <Text style={[styles.textButton, pressed && styles.muted]}>{title}</Text>}
    </Pressable>
  );
}

/** A second action next to the main one ("+15 s", "Skip rest"): outlined, same height
 * family, so it's easy to hit with a sweaty thumb. */
export function OutlineButton({
  title,
  onPress,
  disabled,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [styles.outline, disabled && styles.off, pressed && styles.pressed]}
    >
      <Text style={styles.outlineText}>{title}</Text>
    </Pressable>
  );
}

/** How far through something is, 0 to 1. */
export function ProgressBar({ value }: { value: number }) {
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  return (
    <View
      style={styles.track}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: percent }}
    >
      <View style={[styles.fill, { width: `${percent}%` }]} />
    </View>
  );
}

/** A panel that slides up over the screen (choices, "How to do it", editing a set).
 * Tapping outside it or the phone's back button closes it. */
export function Sheet({
  visible,
  onClose,
  children,
}: {
  visible: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel="Close" />
      <SafeAreaView style={styles.sheet} edges={['bottom']}>
        <ScrollView contentContainerStyle={styles.sheetBody} keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

/** A number with big − and + buttons, and the number itself typeable: reps, kg, seconds.
 * `value` null shows "–" (not filled in yet). */
export function Stepper({
  label,
  value,
  unit,
  onStep,
  onType,
}: {
  label: string;
  value: number | null;
  unit: string;
  onStep: (direction: -1 | 1) => void;
  onType: (value: number | null) => void;
}) {
  return (
    <View style={styles.stepper}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.stepperRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Less ${label.toLowerCase()}`}
          onPress={() => onStep(-1)}
          style={({ pressed }) => [styles.stepButton, pressed && styles.pressed]}
        >
          <Text style={styles.stepSign}>−</Text>
        </Pressable>
        <View style={styles.stepValue}>
          <TextInput
            accessibilityLabel={label}
            value={value === null ? '' : String(value)}
            placeholder="–"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            onChangeText={(text) => {
              const cleaned = text.replace(',', '.').trim();
              const number = Number(cleaned);
              onType(cleaned === '' || Number.isNaN(number) ? null : Math.max(0, number));
            }}
            style={styles.stepInput}
            selectTextOnFocus
          />
          <Text style={styles.stepUnit}>{unit}</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`More ${label.toLowerCase()}`}
          onPress={() => onStep(1)}
          style={({ pressed }) => [styles.stepButton, pressed && styles.pressed]}
        >
          <Text style={styles.stepSign}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

/** One answer of a question. `selected` shows it's picked (and tells screen readers). */
export function Choice({
  label,
  selected,
  onPress,
  multi,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  /** Multi-choice answers are checkboxes for screen readers; single ones are radios. */
  multi?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole={multi ? 'checkbox' : 'radio'}
      accessibilityState={multi ? { checked: selected } : { selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.choice, selected && styles.choiceOn, pressed && styles.pressed]}
    >
      <Text style={[styles.choiceText, selected && styles.choiceTextOn]}>{label}</Text>
    </Pressable>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Gap({ size = 'm' }: { size?: keyof typeof space }) {
  return <View style={{ height: space[size] }} />;
}

export function Loading({ message }: { message?: string }) {
  return (
    <SafeAreaView style={[styles.screen, styles.center]}>
      <ActivityIndicator color={colors.text} size="large" />
      {message ? <Text style={[styles.body_text, styles.muted, styles.centerText]}>{message}</Text> : null}
    </SafeAreaView>
  );
}

export function ErrorView({
  message,
  onRetry,
  retryTitle = 'Try again',
}: {
  message: string;
  onRetry: () => void;
  retryTitle?: string;
}) {
  return (
    <SafeAreaView style={[styles.screen, styles.center, styles.padded]}>
      <Text style={[styles.title, styles.centerText]}>Hold on</Text>
      <Text style={[styles.body_text, styles.centerText]}>{message}</Text>
      <Gap size="l" />
      <LockInButton title={retryTitle} onPress={onRetry} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  body: { padding: space.l, gap: space.m, flexGrow: 1 },
  footer: { paddingHorizontal: space.l, paddingBottom: space.m, paddingTop: space.s },
  center: { alignItems: 'center', justifyContent: 'center', gap: space.m },
  padded: { padding: space.l },
  centerText: { textAlign: 'center' },
  title: { color: colors.text, fontSize: 30, fontWeight: '800', letterSpacing: -0.5 },
  body_text: { color: colors.text, fontSize: 17, lineHeight: 24 },
  label: {
    color: colors.muted,
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  muted: { color: colors.muted },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 14,
    minHeight: 58,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.l,
  },
  primaryText: { color: colors.onPrimary, fontSize: 18, fontWeight: '800', letterSpacing: 0.5 },
  off: { opacity: 0.35 },
  pressed: { opacity: 0.7 },
  textButton: { color: colors.text, fontSize: 16, fontWeight: '600', paddingVertical: space.s },
  choice: {
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: 14,
    paddingVertical: 18,
    paddingHorizontal: space.m,
  },
  choiceOn: { borderColor: colors.primary, backgroundColor: colors.primary },
  choiceText: { color: colors.text, fontSize: 17, fontWeight: '600' },
  choiceTextOn: { color: colors.onPrimary },
  outline: {
    borderColor: colors.text,
    borderWidth: 1.5,
    borderRadius: 14,
    minHeight: 50,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.m,
    flexGrow: 1,
  },
  outlineText: { color: colors.text, fontSize: 16, fontWeight: '700' },
  track: { height: 6, borderRadius: 3, backgroundColor: colors.border, overflow: 'hidden' },
  fill: { height: 6, backgroundColor: colors.primary },
  scrim: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)' },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderColor: colors.border,
    borderWidth: 1,
    maxHeight: '85%',
  },
  sheetBody: { padding: space.l, gap: space.m },
  stepper: { gap: space.s },
  stepperRow: { flexDirection: 'row', alignItems: 'center', gap: space.m },
  stepButton: {
    width: 56,
    height: 56,
    borderRadius: 28,
    borderWidth: 1.5,
    borderColor: colors.text,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepSign: { color: colors.text, fontSize: 28, fontWeight: '600', lineHeight: 32 },
  stepValue: { flex: 1, flexDirection: 'row', alignItems: 'baseline', justifyContent: 'center', gap: space.xs },
  stepInput: { color: colors.text, fontSize: 34, fontWeight: '800', minWidth: 60, textAlign: 'center', padding: 0 },
  stepUnit: { color: colors.muted, fontSize: 16, fontWeight: '600' },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: space.m,
    gap: space.s,
  },
});

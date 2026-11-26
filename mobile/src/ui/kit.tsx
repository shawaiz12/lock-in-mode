/**
 * The app's building blocks in the Lock In look (ADR 0036): chunky cards with a thicker
 * bottom "lip", a big orange button that presses down, Rubik type, light or dark from the
 * phone (src/ui/theme.ts). Screens combine these instead of styling from scratch, so
 * every screen looks and behaves the same.
 * .NET/Unity: like a set of prefabs (or Blazor components) that read a shared theme.
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
  Switch,
  Text,
  TextInput,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { chunky, font, makeStyles, space, type, usePalette } from '@/ui/theme';

export { space, usePalette };

/** A full screen: safe from notches, scrollable body, optional fixed bottom area
 * (the big "Lock In" button lives there, always in reach of a thumb). `header` stays
 * at the top while the body scrolls. */
export function Screen({
  children,
  footer,
  header,
}: {
  children: ReactNode;
  footer?: ReactNode;
  header?: ReactNode;
}) {
  const styles = useStyles();
  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      {header ? <View style={styles.header}>{header}</View> : null}
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {children}
      </ScrollView>
      {footer ? <View style={styles.footer}>{footer}</View> : null}
    </SafeAreaView>
  );
}

export function Title({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return (
    <Text style={styles.title} accessibilityRole="header">
      {children}
    </Text>
  );
}

export function Heading({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return <Text style={styles.heading}>{children}</Text>;
}

export function Body({ children, muted }: { children: ReactNode; muted?: boolean }) {
  const styles = useStyles();
  return <Text style={[styles.bodyText, muted && styles.muted]}>{children}</Text>;
}

export function Label({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return <Text style={styles.label}>{children}</Text>;
}

/** The main action of a screen. Its words say what happens ("Lock In", not "Next").
 * `detail`: a smaller second line ("Pull · about 45 min"). It presses down like a key. */
export function LockInButton({
  title,
  detail,
  onPress,
  disabled,
  busy,
  tone = 'brand',
}: {
  title: string;
  detail?: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
  /** 'danger': red, for "Delete for good" only. */
  tone?: 'brand' | 'danger';
}) {
  const styles = useStyles();
  const palette = usePalette();
  const off = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: off, busy }}
      onPress={onPress}
      disabled={off}
      style={({ pressed }) => [
        styles.primary,
        tone === 'danger' && styles.dangerButton,
        off && styles.off,
        pressed && styles.primaryDown,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={palette.onButton} />
      ) : (
        <>
          <Text style={styles.primaryText}>{title}</Text>
          {detail ? <Text style={styles.primaryDetail}>{detail}</Text> : null}
        </>
      )}
    </Pressable>
  );
}

/** A quieter button: back, skip, small choices. */
export function TextButton({ title, onPress }: { title: string; onPress: () => void }) {
  const styles = useStyles();
  return (
    <Pressable accessibilityRole="button" onPress={onPress} hitSlop={12}>
      {({ pressed }) => <Text style={[styles.textButton, pressed && styles.muted]}>{title}</Text>}
    </Pressable>
  );
}

/** A second action next to the main one ("+15 s", "Skip rest"): a chunky card-coloured
 * key, big enough for a sweaty thumb. */
export function OutlineButton({
  title,
  onPress,
  disabled,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [styles.outline, disabled && styles.off, pressed && styles.keyDown]}
    >
      <Text style={styles.outlineText}>{title}</Text>
    </Pressable>
  );
}

/** A small chunky key with a word: "‹ Leave", "More". */
export function SmallKey({ title, onPress }: { title: string; onPress: () => void }) {
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => [styles.smallKey, pressed && styles.keyDown]}
    >
      <Text style={styles.smallKeyText}>{title}</Text>
    </Pressable>
  );
}

/** A square key with an icon: back, settings. */
export function IconButton({
  label,
  onPress,
  children,
}: {
  label: string;
  onPress: () => void;
  children: ReactNode;
}) {
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => [styles.iconButton, pressed && styles.keyDown]}
    >
      {children}
    </Pressable>
  );
}

export function BackIcon() {
  const palette = usePalette();
  return (
    <Svg width={20} height={20} viewBox="0 0 24 24" fill="none">
      <Path d="M15 5l-7 7 7 7" stroke={palette.text} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}

export function BackButton({ onPress }: { onPress: () => void }) {
  return (
    <IconButton label="Back" onPress={onPress}>
      <BackIcon />
    </IconButton>
  );
}

/** How far through something is, 0 to 1: a thick outlined bar. Gold for XP. */
export function ProgressBar({ value, tone = 'brand' }: { value: number; tone?: 'brand' | 'gold' }) {
  const styles = useStyles();
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  return (
    <View
      style={styles.track}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: percent }}
    >
      <View style={[styles.fill, tone === 'gold' && styles.fillGold, { width: `${percent}%` }]} />
    </View>
  );
}

/** The top of a step-by-step flow: back (if there's somewhere to go), the bar, "4 / 8". */
export function StepHeader({ step, of, onBack }: { step: number; of: number; onBack?: () => void }) {
  const styles = useStyles();
  return (
    <View style={styles.stepHeader}>
      {onBack ? <BackButton onPress={onBack} /> : null}
      <View style={styles.grow}>
        <ProgressBar value={step / of} />
      </View>
      <Text style={styles.stepCount}>
        {step} / {of}
      </Text>
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
  const styles = useStyles();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel="Close" />
      <SafeAreaView style={styles.sheet} edges={['bottom']}>
        <View style={styles.handle} />
        <ScrollView contentContainerStyle={styles.sheetBody} keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

/** A number with big − and + keys, and the number itself typeable: reps, kg, seconds.
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
  const styles = useStyles();
  const palette = usePalette();
  return (
    <View style={styles.stepper}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.stepperRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Less ${label.toLowerCase()}`}
          onPress={() => onStep(-1)}
          style={({ pressed }) => [styles.stepButton, pressed && styles.keyDown]}
        >
          <Text style={styles.stepSign}>−</Text>
        </Pressable>
        <View style={styles.stepValue}>
          <TextInput
            accessibilityLabel={label}
            value={value === null ? '' : String(value)}
            placeholder="–"
            placeholderTextColor={palette.muted}
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
          style={({ pressed }) => [styles.stepButton, pressed && styles.keyDown]}
        >
          <Text style={styles.stepSign}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

/** A tick in a filled circle: a picked answer, a done set. */
export function Tick({ size = 26 }: { size?: number }) {
  const palette = usePalette();
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Path d="M12 1a11 11 0 1 1 0 22 11 11 0 0 1 0-22z" fill={palette.button} />
      <Path d="M7 12.5l3 3 7-7" fill="none" stroke="#FFFFFF" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}

/** One answer of a question. `selected` shows it's picked (and tells screen readers).
 * `badge`: a number or short mark in front ("3"); `hint`: a smaller second line. */
export function Choice({
  label,
  selected,
  onPress,
  multi,
  badge,
  hint,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  /** Multi-choice answers are checkboxes for screen readers; single ones are radios. */
  multi?: boolean;
  badge?: string;
  hint?: string;
}) {
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole={multi ? 'checkbox' : 'radio'}
      accessibilityState={multi ? { checked: selected } : { selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.choice, selected && styles.choiceOn, pressed && styles.keyDown]}
    >
      {badge ? (
        <View style={[styles.badge, selected && styles.badgeOn]}>
          <Text style={[styles.badgeText, selected && styles.badgeTextOn]}>{badge}</Text>
        </View>
      ) : null}
      <View style={styles.grow}>
        <Text style={[styles.choiceText, selected && styles.choiceTextOn]}>{label}</Text>
        {hint ? <Text style={[styles.choiceHint, selected && styles.choiceTextOn]}>{hint}</Text> : null}
      </View>
      {selected ? <Tick /> : null}
    </Pressable>
  );
}

/** A small rounded tag ("Mid chest"). */
export function Chip({ label }: { label: string }) {
  const styles = useStyles();
  return (
    <View style={styles.chip}>
      <Text style={styles.chipText}>{label}</Text>
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const styles = useStyles();
  return <View style={[styles.card, style]}>{children}</View>;
}

/** A card holding rows (Settings). */
export function RowGroup({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return <View style={styles.rowGroup}>{children}</View>;
}

/** One tappable row: "Reminder ............ Mon, Wed · 6:30 pm". */
export function Row({
  title,
  value,
  onPress,
  danger,
  icon,
  last,
}: {
  title: string;
  value?: string;
  onPress: () => void;
  danger?: boolean;
  icon?: ReactNode;
  last?: boolean;
}) {
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.row, !last && styles.rowLine, pressed && styles.rowDown]}
    >
      {icon}
      <Text style={[styles.rowTitle, danger && styles.danger]}>{title}</Text>
      {value ? <Text style={styles.rowValue}>{value}</Text> : null}
    </Pressable>
  );
}

/** A row with an on/off switch. */
export function SwitchRow({
  title,
  value,
  onChange,
  disabled,
  last,
}: {
  title: string;
  value: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  last?: boolean;
}) {
  const styles = useStyles();
  const palette = usePalette();
  return (
    <View style={[styles.row, !last && styles.rowLine]}>
      <Text style={styles.rowTitle}>{title}</Text>
      <Switch
        accessibilityLabel={title}
        value={value}
        onValueChange={onChange}
        disabled={disabled}
        trackColor={{ false: palette.track, true: palette.button }}
        thumbColor="#FFFFFF"
      />
    </View>
  );
}

export function Gap({ size = 'm' }: { size?: keyof typeof space }) {
  return <View style={{ height: space[size] }} />;
}

export function Loading({ message }: { message?: string }) {
  const styles = useStyles();
  const palette = usePalette();
  return (
    <SafeAreaView style={[styles.screen, styles.center]}>
      <ActivityIndicator color={palette.brand} size="large" />
      {message ? <Text style={[styles.bodyText, styles.muted, styles.centerText]}>{message}</Text> : null}
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
  const styles = useStyles();
  return (
    <SafeAreaView style={[styles.screen, styles.center, styles.padded]}>
      <Text style={[styles.title, styles.centerText]}>Hold on</Text>
      <Text style={[styles.bodyText, styles.centerText]}>{message}</Text>
      <Gap size="l" />
      <View style={styles.wide}>
        <LockInButton title={retryTitle} onPress={onRetry} />
      </View>
    </SafeAreaView>
  );
}

const useStyles = makeStyles((p) => ({
  screen: { flex: 1, backgroundColor: p.ground },
  header: { paddingHorizontal: space.m, paddingTop: space.s, paddingBottom: space.xs },
  body: { padding: space.m, gap: 12, flexGrow: 1 },
  footer: { paddingHorizontal: space.m, paddingBottom: space.m, paddingTop: space.s, gap: space.s },
  center: { alignItems: 'center', justifyContent: 'center', gap: space.m },
  padded: { padding: space.l },
  wide: { alignSelf: 'stretch' },
  grow: { flex: 1 },
  centerText: { textAlign: 'center' },
  title: { ...type.title, color: p.text },
  heading: { ...type.heading, color: p.text },
  bodyText: { ...type.body, color: p.text },
  label: { ...type.label, color: p.muted },
  muted: { color: p.muted },
  danger: { color: p.danger },
  primary: {
    backgroundColor: p.button,
    borderRadius: 20,
    minHeight: 64,
    borderBottomWidth: 6,
    borderBottomColor: p.buttonLip,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.l,
    paddingVertical: 8,
  },
  dangerButton: { backgroundColor: '#B3261E', borderBottomColor: '#7A1A14' },
  primaryDown: { borderBottomWidth: 2, marginTop: 4, minHeight: 60 },
  primaryText: { fontFamily: font.heavy, color: p.onButton, fontSize: 19, textAlign: 'center' },
  primaryDetail: { fontFamily: font.semibold, color: p.onButton, fontSize: 13, marginTop: 2 },
  off: { opacity: 0.4 },
  keyDown: { borderBottomWidth: 2, marginTop: 3 },
  textButton: { fontFamily: font.semibold, color: p.text, fontSize: 16, paddingVertical: space.s },
  choice: {
    ...chunky,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderColor: p.edge,
    backgroundColor: p.card,
    borderRadius: 18,
    minHeight: 62,
    paddingVertical: 12,
    paddingHorizontal: 14,
  },
  choiceOn: { borderColor: p.brand, backgroundColor: p.chip },
  choiceText: { fontFamily: font.bold, color: p.text, fontSize: 17 },
  choiceHint: { fontFamily: font.regular, color: p.muted, fontSize: 14, marginTop: 2 },
  choiceTextOn: { color: p.chipText },
  badge: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: p.ground,
    borderWidth: 2,
    borderColor: p.edge,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeOn: { backgroundColor: p.button, borderColor: p.button },
  badgeText: { fontFamily: font.heavy, color: p.text, fontSize: 17 },
  badgeTextOn: { color: p.onButton },
  chip: { backgroundColor: p.chip, borderRadius: 999, paddingVertical: 5, paddingHorizontal: 10 },
  chipText: { fontFamily: font.bold, color: p.chipText, fontSize: 13 },
  outline: {
    ...chunky,
    borderColor: p.edge,
    backgroundColor: p.card,
    borderRadius: 18,
    minHeight: 54,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.m,
    flexGrow: 1,
  },
  outlineText: { fontFamily: font.bold, color: p.text, fontSize: 16 },
  smallKey: {
    height: 44,
    paddingHorizontal: 14,
    borderRadius: 14,
    borderWidth: 2,
    borderBottomWidth: 4,
    borderColor: p.edge,
    backgroundColor: p.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  smallKeyText: { fontFamily: font.bold, color: p.text, fontSize: 15 },
  iconButton: {
    width: 44,
    height: 44,
    borderRadius: 14,
    borderWidth: 2,
    borderBottomWidth: 4,
    borderColor: p.edge,
    backgroundColor: p.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  track: {
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    borderColor: p.outline,
    backgroundColor: p.track,
    overflow: 'hidden',
  },
  fill: { height: '100%', backgroundColor: p.brand },
  fillGold: { backgroundColor: p.gold },
  stepHeader: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 44 },
  stepCount: { fontFamily: font.bold, color: p.muted, fontSize: 13 },
  scrim: { flex: 1, backgroundColor: p.scrim },
  sheet: {
    backgroundColor: p.card,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderColor: p.edge,
    borderWidth: 2,
    maxHeight: '88%',
  },
  handle: { alignSelf: 'center', width: 44, height: 5, borderRadius: 3, backgroundColor: p.edge, marginTop: 8 },
  sheetBody: { padding: space.l, gap: 12 },
  stepper: { gap: space.s },
  stepperRow: { flexDirection: 'row', alignItems: 'center', gap: space.m },
  stepButton: {
    ...chunky,
    width: 58,
    height: 58,
    borderRadius: 18,
    borderColor: p.edge,
    backgroundColor: p.ground,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepSign: { fontFamily: font.bold, color: p.text, fontSize: 28, lineHeight: 32 },
  stepValue: { flex: 1, flexDirection: 'row', alignItems: 'baseline', justifyContent: 'center', gap: space.xs },
  stepInput: { fontFamily: font.heavy, color: p.text, fontSize: 42, minWidth: 60, textAlign: 'center', padding: 0 },
  stepUnit: { fontFamily: font.bold, color: p.muted, fontSize: 16 },
  card: {
    ...chunky,
    backgroundColor: p.card,
    borderColor: p.edge,
    borderRadius: 20,
    padding: 14,
    gap: space.s,
  },
  rowGroup: { ...chunky, backgroundColor: p.card, borderColor: p.edge, borderRadius: 20, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingHorizontal: 14 },
  rowLine: { borderBottomWidth: 2, borderBottomColor: p.line },
  rowDown: { backgroundColor: p.line },
  rowTitle: { flex: 1, fontFamily: font.bold, color: p.text, fontSize: 16 },
  rowValue: { fontFamily: font.regular, color: p.muted, fontSize: 14, flexShrink: 1, textAlign: 'right' },
}));

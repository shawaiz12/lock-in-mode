/**
 * The look (ADR 0036, lock-in-mode/ui-redesign.md): warm cream in light mode, pure black
 * in dark mode, an orange that pops, gold only for rewards (streak, XP, bests). Light or
 * dark follows the phone's setting.
 *
 * Every colour has a ROLE ("card", "muted text"), never a name like "orange", so a screen
 * says what a thing is and the palette decides how it looks in each mode.
 * .NET/Unity: like a ScriptableObject theme (or a XAML ResourceDictionary) swapped at
 * runtime, with styles that read from it.
 */
import {
  Rubik_400Regular,
  Rubik_500Medium,
  Rubik_600SemiBold,
  Rubik_700Bold,
  Rubik_800ExtraBold,
} from '@expo-google-fonts/rubik';
import { StyleSheet, useColorScheme } from 'react-native';

export type Palette = {
  dark: boolean;
  /** The screen behind everything. */
  ground: string;
  card: string;
  /** A card's 2 px edge and its thicker bottom "lip" (the chunky, pressable look). */
  edge: string;
  /** Thin dividers inside a card. */
  line: string;
  /** The empty part of a bar or a ring. */
  track: string;
  text: string;
  muted: string;
  /** Rings, icons, the muscle map: the brand orange (#E14705, his pick). */
  brand: string;
  /** The main button: a touch darker than the brand so white text passes 4.5:1. */
  button: string;
  onButton: string;
  buttonLip: string;
  /** Rewards only: streak, XP, new bests. */
  gold: string;
  /** Gold as text (gold on cream is too faint to read). */
  goldText: string;
  /** The outline around bars and the flame (gold on cream needs it). */
  outline: string;
  /** A picked answer or a tag. */
  chip: string;
  chipText: string;
  danger: string;
  scrim: string;
  /** The world card on Home. */
  world: { sky: string; sun: string; hill: string; hillBack: string; cloud: string };
};

export const LIGHT: Palette = {
  dark: false,
  ground: '#FFE9BD',
  card: '#FFF6E3',
  edge: '#EBCB8F',
  line: '#F3E2BF',
  track: '#F3D9A4',
  text: '#2B2118',
  muted: '#6B5B49',
  brand: '#E14705',
  button: '#D44204',
  onButton: '#FFFFFF',
  buttonLip: '#A33203',
  gold: '#FFB800',
  goldText: '#8A5A00',
  outline: '#2B2118',
  chip: '#FBD3B5',
  chipText: '#7A2802',
  danger: '#B3261E',
  scrim: 'rgba(43, 33, 24, 0.55)',
  world: { sky: '#FFD7AE', sun: '#FFC94D', hill: '#8CC46A', hillBack: '#B7D98C', cloud: '#FFF6E3' },
};

export const DARK: Palette = {
  dark: true,
  ground: '#000000',
  card: '#141414',
  edge: '#2A2A2A',
  line: '#1F1F1F',
  track: '#262626',
  text: '#FFFFFF',
  muted: '#A6A6A6',
  brand: '#E14705',
  button: '#D44204',
  onButton: '#FFFFFF',
  buttonLip: '#8F2C02',
  gold: '#FFB800',
  goldText: '#FFB800',
  outline: '#262626',
  chip: '#2A1206',
  chipText: '#FFB48A',
  danger: '#FF6B5E',
  scrim: 'rgba(0, 0, 0, 0.7)',
  world: { sky: '#2A1408', sun: '#FFB45C', hill: '#2E4A26', hillBack: '#3D5E32', cloud: '#1E1E1E' },
};

/** The pact is a paper card: the same in both modes. */
export const PAPER = { paper: '#FFFBF2', ink: '#2B2118', faint: '#6B5B49', rule: '#E3C998', accent: '#B83A04', stamp: '#C43C03' };

/** The palette for the phone's light or dark setting. */
export function usePalette(): Palette {
  return useColorScheme() === 'dark' ? DARK : LIGHT;
}

/** Styles that depend on the palette, made once per mode and reused (a StyleSheet per
 * mode, not per draw). Use it outside components:
 *   const useStyles = makeStyles((p) => ({ box: { backgroundColor: p.card } }));
 * and call `useStyles()` inside one. */
type StyleSet = Parameters<typeof StyleSheet.create>[0];

export function makeStyles<S extends StyleSet>(make: (p: Palette) => S & StyleSet): () => Readonly<S> {
  const made = new Map<Palette, Readonly<S>>();
  return function useStyles(): Readonly<S> {
    const palette = usePalette();
    const cached = made.get(palette);
    if (cached) return cached;
    const styles = StyleSheet.create(make(palette));
    made.set(palette, styles);
    return styles;
  };
}

/** Rubik: bold and slightly rounded (his pick). Each weight is its own font file, so a
 * style picks the family, not `fontWeight` (Android can't pick a weight by itself). */
export const font = {
  regular: 'Rubik_400Regular',
  medium: 'Rubik_500Medium',
  semibold: 'Rubik_600SemiBold',
  bold: 'Rubik_700Bold',
  heavy: 'Rubik_800ExtraBold',
} as const;

/** For `useFonts` in the root layout. */
export const FONT_FILES = {
  Rubik_400Regular,
  Rubik_500Medium,
  Rubik_600SemiBold,
  Rubik_700Bold,
  Rubik_800ExtraBold,
};

/** Type sizes from the design system: number 56, title 30, heading 20, body 17, label 13. */
export const type = {
  number: { fontFamily: font.heavy, fontSize: 56, letterSpacing: -1 },
  title: { fontFamily: font.heavy, fontSize: 30, letterSpacing: -0.5, lineHeight: 36 },
  heading: { fontFamily: font.bold, fontSize: 20, lineHeight: 26 },
  body: { fontFamily: font.regular, fontSize: 17, lineHeight: 24 },
  small: { fontFamily: font.regular, fontSize: 14, lineHeight: 20 },
  label: { fontFamily: font.bold, fontSize: 13, letterSpacing: 0.8, textTransform: 'uppercase' as const },
} as const;

export const space = { xs: 4, s: 8, m: 16, l: 24, xl: 32 };

/** The chunky piece: a 2 px edge and a thicker bottom lip. */
export const chunky = { borderWidth: 2, borderBottomWidth: 5 } as const;

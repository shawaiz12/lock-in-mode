/**
 * The muscle map on Home (ADR 0036): a front and a back body, each muscle group filled in
 * orange once this week trained it, outlined if the next workout trains it. Tap it for
 * every head ("Side delts · 3 sets", "Rear delts · Not yet"), because every head counts
 * (his rule: each workout covers all heads of the muscles it trains).
 *
 * A simple drawing, not anatomy: it shows where this week's work went at a glance.
 * .NET/Unity: like a UI Image per region whose colour is set from data.
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import Svg, { Circle, Ellipse, Path, Rect } from 'react-native-svg';

import { getMuscles, type MuscleGroup, type Muscles } from '@/api/endpoints';
import {
  type AreaState,
  areaState,
  GROUP_NAMES,
  HEAD_NAMES,
  mapLabel,
  nextLine,
  setsText,
  trainedLine,
} from '@/features/muscles/words';
import { keys } from '@/state/startup';
import { Body, Chip, Heading, Label, Sheet, TextButton, Title } from '@/ui/kit';
import { chunky, font, makeStyles, type Palette, space, usePalette } from '@/ui/theme';

type Shape =
  | { kind: 'rect'; x: number; y: number; w: number; h: number; r?: number }
  | { kind: 'ellipse'; cx: number; cy: number; rx: number; ry: number }
  | { kind: 'circle'; cx: number; cy: number; r: number }
  | { kind: 'path'; d: string };
type Area = { group: MuscleGroup | null; shapes: Shape[] };

const HEAD: Area = {
  group: null,
  shapes: [
    { kind: 'circle', cx: 30, cy: 10, r: 8 },
    { kind: 'rect', x: 27, y: 17, w: 6, h: 5, r: 2 },
  ],
};
const pair = (left: Shape, dx: number): Shape[] => {
  if (left.kind === 'rect') return [left, { ...left, x: left.x + dx }];
  if (left.kind === 'ellipse') return [left, { ...left, cx: left.cx + dx }];
  if (left.kind === 'circle') return [left, { ...left, cx: left.cx + dx }];
  return [left];
};

export const FRONT: Area[] = [
  HEAD,
  { group: 'shoulders', shapes: pair({ kind: 'circle', cx: 16, cy: 27, r: 6 }, 28) },
  { group: 'chest', shapes: pair({ kind: 'ellipse', cx: 24.5, cy: 32, rx: 7, ry: 6 }, 11) },
  { group: 'biceps', shapes: pair({ kind: 'rect', x: 9, y: 33, w: 7, h: 16, r: 3 }, 35) },
  { group: 'forearms', shapes: pair({ kind: 'rect', x: 7, y: 51, w: 6, h: 17, r: 3 }, 40) },
  { group: 'core', shapes: [{ kind: 'rect', x: 22, y: 39, w: 16, h: 22, r: 4 }] },
  { group: 'quads', shapes: pair({ kind: 'rect', x: 19.5, y: 64, w: 9, h: 28, r: 4 }, 12) },
  { group: 'adductors', shapes: [{ kind: 'rect', x: 28.5, y: 64, w: 3, h: 16, r: 1.5 }] },
  { group: 'calves', shapes: pair({ kind: 'rect', x: 21, y: 96, w: 7, h: 20, r: 3 }, 11) },
];

export const BACK: Area[] = [
  HEAD,
  { group: 'traps', shapes: [{ kind: 'path', d: 'M21 21 L39 21 L30 35 Z' }] },
  { group: 'shoulders', shapes: pair({ kind: 'circle', cx: 16, cy: 27, r: 6 }, 28) },
  { group: 'back', shapes: [{ kind: 'rect', x: 21, y: 31, w: 18, h: 28, r: 5 }] },
  { group: 'triceps', shapes: pair({ kind: 'rect', x: 9, y: 33, w: 7, h: 16, r: 3 }, 35) },
  { group: 'forearms', shapes: pair({ kind: 'rect', x: 7, y: 51, w: 6, h: 17, r: 3 }, 40) },
  { group: 'glutes', shapes: pair({ kind: 'ellipse', cx: 25, cy: 65, rx: 6, ry: 6 }, 10) },
  { group: 'hamstrings', shapes: pair({ kind: 'rect', x: 19.5, y: 72, w: 9, h: 22, r: 4 }, 12) },
  { group: 'calves', shapes: pair({ kind: 'rect', x: 21, y: 97, w: 7, h: 19, r: 3 }, 11) },
];

function paint(state: AreaState | 'body', palette: Palette) {
  switch (state) {
    case 'trained':
      return { fill: palette.brand };
    case 'next':
      return { fill: palette.chip, stroke: palette.brand, strokeWidth: 1.4, strokeDasharray: '2 1.5' };
    case 'rest':
      return { fill: palette.track };
    case 'body':
      return { fill: palette.edge };
  }
}

function ShapeView({ shape, look }: { shape: Shape; look: ReturnType<typeof paint> }) {
  switch (shape.kind) {
    case 'rect':
      return <Rect x={shape.x} y={shape.y} width={shape.w} height={shape.h} rx={shape.r ?? 0} {...look} />;
    case 'ellipse':
      return <Ellipse cx={shape.cx} cy={shape.cy} rx={shape.rx} ry={shape.ry} {...look} />;
    case 'circle':
      return <Circle cx={shape.cx} cy={shape.cy} r={shape.r} {...look} />;
    case 'path':
      return <Path d={shape.d} {...look} />;
  }
}

export function BodyFigure({ areas, muscles, height = 104 }: { areas: Area[]; muscles: Muscles; height?: number }) {
  const palette = usePalette();
  const byGroup = new Map(muscles.groups.map((g) => [g.group, g]));
  return (
    <Svg width={(height * 60) / 124} height={height} viewBox="0 0 60 124">
      {areas.map((area, i) => {
        const look = paint(area.group ? areaState(byGroup.get(area.group)) : 'body', palette);
        return area.shapes.map((shape, j) => <ShapeView key={`${i}-${j}`} shape={shape} look={look} />);
      })}
    </Svg>
  );
}

/** Home's card. Nothing until the first answer arrives (it's below the fold). */
export function MuscleMapCard() {
  const styles = useStyles();
  const muscles = useQuery({ queryKey: keys.muscles, queryFn: getMuscles });
  const [open, setOpen] = useState(false);
  if (!muscles.data) return null;
  const data = muscles.data;
  const next = nextLine(data);
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={mapLabel(data)}
        accessibilityHint="Shows every muscle and head"
        onPress={() => setOpen(true)}
        style={({ pressed }) => [styles.card, pressed && styles.down]}
      >
        <View style={styles.bodies} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
          <BodyFigure areas={FRONT} muscles={data} />
          <BodyFigure areas={BACK} muscles={data} />
        </View>
        <View style={styles.grow}>
          <Label>Muscles this week</Label>
          <Text style={styles.trained}>{trainedLine(data)}</Text>
          {next ? <Text style={styles.next}>{next}</Text> : null}
          <Text style={styles.more}>See every muscle ›</Text>
        </View>
      </Pressable>
      <MusclesSheet muscles={data} visible={open} onClose={() => setOpen(false)} />
    </>
  );
}

function MusclesSheet({ muscles, visible, onClose }: { muscles: Muscles; visible: boolean; onClose: () => void }) {
  const styles = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose}>
      <Title>Muscles this week</Title>
      <Body muted>Sets that trained each muscle since Monday. Warm-ups don’t count.</Body>
      <View style={styles.legend}>
        <View style={[styles.swatch, styles.swatchTrained]} />
        <Text style={styles.legendText}>Trained</Text>
        <View style={[styles.swatch, styles.swatchNext]} />
        <Text style={styles.legendText}>Next workout</Text>
      </View>
      {muscles.groups.map((group) => (
        <View key={group.group} style={styles.group}>
          <View style={styles.groupTop}>
            <Heading>{GROUP_NAMES[group.group]}</Heading>
            {group.next_up ? <Chip label="Next up" /> : null}
            <Text style={[styles.sets, group.sets > 0 && styles.setsOn]}>{setsText(group.sets)}</Text>
          </View>
          {group.heads.map((head) => (
            <View key={head.head} style={styles.head}>
              <Text style={styles.headName}>{HEAD_NAMES[head.head]}</Text>
              <Text style={[styles.headSets, head.sets > 0 && styles.setsOn]}>{setsText(head.sets)}</Text>
            </View>
          ))}
        </View>
      ))}
      <TextButton title="Close" onPress={onClose} />
    </Sheet>
  );
}

const useStyles = makeStyles((p) => ({
  card: {
    ...chunky,
    backgroundColor: p.card,
    borderColor: p.edge,
    borderRadius: 20,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  down: { borderBottomWidth: 2, marginTop: 3 },
  bodies: { flexDirection: 'row', gap: 4 },
  grow: { flex: 1, gap: 3 },
  trained: { fontFamily: font.bold, color: p.text, fontSize: 15, lineHeight: 20 },
  next: { fontFamily: font.regular, color: p.muted, fontSize: 13, lineHeight: 18 },
  more: { fontFamily: font.bold, color: p.chipText, fontSize: 13, marginTop: 2 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  swatch: { width: 14, height: 14, borderRadius: 4 },
  swatchTrained: { backgroundColor: p.brand },
  swatchNext: { backgroundColor: p.chip, borderWidth: 1.5, borderColor: p.brand, borderStyle: 'dashed' },
  legendText: { fontFamily: font.regular, color: p.muted, fontSize: 13, marginRight: space.s },
  group: { borderTopWidth: 2, borderTopColor: p.line, paddingTop: 10, gap: 4 },
  groupTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sets: { marginLeft: 'auto', fontFamily: font.bold, color: p.muted, fontSize: 14 },
  setsOn: { color: p.chipText },
  head: { flexDirection: 'row', justifyContent: 'space-between', paddingLeft: 4 },
  headName: { fontFamily: font.regular, color: p.text, fontSize: 15 },
  headSets: { fontFamily: font.regular, color: p.muted, fontSize: 14 },
}));

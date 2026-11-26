/**
 * The muscle map's words (ADR 0036): plain names for every muscle group and head the
 * server sends (GET /me/muscles), and the lines on Home's card. Pure, no React.
 * The `Record<…>` types make TypeScript fail if the server adds a muscle we have no name
 * for (like a C# switch expression that must cover every enum value).
 */
import type { MuscleGroup, MuscleHead, Muscles } from '@/api/endpoints';

export const GROUP_NAMES: Record<MuscleGroup, string> = {
  chest: 'Chest',
  back: 'Back',
  shoulders: 'Shoulders',
  traps: 'Traps',
  biceps: 'Biceps',
  triceps: 'Triceps',
  forearms: 'Forearms',
  quads: 'Quads',
  hamstrings: 'Hamstrings',
  glutes: 'Glutes',
  adductors: 'Inner thighs',
  calves: 'Calves',
  core: 'Core',
};

export const HEAD_NAMES: Record<MuscleHead, string> = {
  chest_upper: 'Upper chest',
  chest_mid: 'Mid chest',
  chest_lower: 'Lower chest',
  delt_front: 'Front delts',
  delt_side: 'Side delts',
  delt_rear: 'Rear delts',
  biceps_long: 'Long head (outer)',
  biceps_short: 'Short head (inner)',
  brachialis: 'Brachialis',
  triceps_long: 'Long head',
  triceps_lateral: 'Lateral head',
  triceps_medial: 'Medial head',
  lats: 'Lats',
  mid_back: 'Mid back',
  spinal_erectors: 'Lower back',
  upper_traps: 'Upper traps',
  lower_traps: 'Lower traps',
  quads_vastus: 'Vastus (front and sides)',
  rectus_femoris: 'Rectus femoris',
  hamstrings_hip: 'Hamstrings (hinges)',
  hamstrings_knee: 'Hamstrings (curls)',
  glute_max: 'Glute max',
  glute_med: 'Glute med (side)',
  gastrocnemius: 'Upper calf',
  soleus: 'Lower calf',
  upper_abs: 'Upper abs',
  lower_abs: 'Lower abs',
  obliques: 'Obliques',
  deep_core: 'Deep core',
  forearm_flexors: 'Forearm flexors',
  forearm_extensors: 'Forearm extensors',
  brachioradialis: 'Brachioradialis',
  adductors: 'Adductors',
};

type Group = Muscles['groups'][number];

/** "Chest, shoulders, triceps" from names in the server's order. */
function list(groups: Group[]): string {
  return groups
    .map((g, i) => (i === 0 ? GROUP_NAMES[g.group] : GROUP_NAMES[g.group].toLowerCase()))
    .join(', ');
}

/** What this week trained, or what to say before the first workout. */
export function trainedLine(muscles: Muscles): string {
  const trained = muscles.groups.filter((g) => g.sets > 0);
  return trained.length > 0 ? list(trained) : 'Nothing yet this week';
}

/** "Next up: back, biceps": what the next workout trains. null when there's none. */
export function nextLine(muscles: Muscles): string | null {
  const next = muscles.groups.filter((g) => g.next_up);
  if (next.length === 0) return null;
  const words = list(next);
  return `Next up: ${words.charAt(0).toLowerCase()}${words.slice(1)}`;
}

export function setsText(sets: number): string {
  if (sets === 0) return 'Not yet';
  return sets === 1 ? '1 set' : `${sets} sets`;
}

/** For screen readers: the map as words. */
export function mapLabel(muscles: Muscles): string {
  const next = nextLine(muscles);
  return `Muscles this week: ${trainedLine(muscles)}.${next ? ` ${next}.` : ''}`;
}

/** How the map colours one area: trained this week, trained next, or neither. */
export type AreaState = 'trained' | 'next' | 'rest';

export function areaState(group: Group | undefined): AreaState {
  if (!group) return 'rest';
  if (group.sets > 0) return 'trained';
  return group.next_up ? 'next' : 'rest';
}

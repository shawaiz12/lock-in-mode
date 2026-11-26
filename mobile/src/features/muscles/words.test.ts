import type { Muscles } from '@/api/endpoints';

import { areaState, GROUP_NAMES, HEAD_NAMES, mapLabel, nextLine, setsText, trainedLine } from './words';

type Group = Muscles['groups'][number];
const group = (name: Group['group'], sets: number, next = false): Group => ({
  group: name,
  sets,
  next_up: next,
  heads: [],
});
const muscles = (...groups: Group[]): Muscles => ({ week_start: '2026-11-23', next_workout: 'Pull', groups });

describe('the muscle map’s words', () => {
  it('lists what was trained in the server’s order', () => {
    expect(trainedLine(muscles(group('chest', 6), group('back', 0), group('triceps', 3)))).toBe('Chest, triceps');
    expect(trainedLine(muscles(group('chest', 0)))).toBe('Nothing yet this week');
  });

  it('says what the next workout trains, or nothing', () => {
    expect(nextLine(muscles(group('back', 0, true), group('biceps', 2, true)))).toBe('Next up: back, biceps');
    expect(nextLine(muscles(group('back', 3)))).toBeNull();
  });

  it('names inner thighs plainly', () => {
    expect(trainedLine(muscles(group('adductors', 1), group('glutes', 1)))).toBe('Inner thighs, glutes');
  });

  it('counts sets in words', () => {
    expect([setsText(0), setsText(1), setsText(7)]).toEqual(['Not yet', '1 set', '7 sets']);
  });

  it('reads the map aloud for screen readers', () => {
    expect(mapLabel(muscles(group('chest', 2), group('back', 0, true)))).toBe(
      'Muscles this week: Chest. Next up: back.',
    );
  });

  it('colours an area: trained beats next, next beats resting', () => {
    expect(areaState(group('chest', 2, true))).toBe('trained');
    expect(areaState(group('chest', 0, true))).toBe('next');
    expect(areaState(group('chest', 0))).toBe('rest');
    expect(areaState(undefined)).toBe('rest');
  });

  it('has a plain name for every group and head', () => {
    for (const name of Object.values(GROUP_NAMES)) expect(name).not.toBe('');
    for (const name of Object.values(HEAD_NAMES)) expect(name).not.toBe('');
    expect(Object.keys(HEAD_NAMES)).toHaveLength(33); // models/enums.py MuscleHead
  });
});

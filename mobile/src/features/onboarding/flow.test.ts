import {
  type Answers,
  chooseLocation,
  displayName,
  echoFor,
  EMPTY_ANSWERS,
  GOALS,
  IncompleteAnswersError,
  isAnswered,
  stepsFor,
  toggle,
  toProfileWrite,
} from './flow';

const complete: Answers = {
  ...EMPTY_ANSWERS,
  goal: 'build_muscle',
  history: 'never_or_on_and_off',
  location: 'gym',
  days: 3,
  minutes: 45,
};

describe('stepsFor', () => {
  it('asks about equipment at home only', () => {
    expect(stepsFor({ ...EMPTY_ANSWERS, location: 'home' })).toContain('equipment');
    expect(stepsFor({ ...EMPTY_ANSWERS, location: 'gym' })).not.toContain('equipment');
    expect(stepsFor(EMPTY_ANSWERS)).not.toContain('equipment');
  });

  it('follows the playbook order', () => {
    expect(stepsFor({ ...EMPTY_ANSWERS, location: 'home' })).toEqual([
      'welcome',
      'goal',
      'echo',
      'history',
      'where',
      'equipment',
      'days',
      'time',
      'limits',
      'obstacles',
    ]);
  });
});

describe('isAnswered', () => {
  it('needs the single-choice answers', () => {
    for (const step of ['goal', 'history', 'where', 'days', 'time'] as const) {
      expect(isAnswered(step, EMPTY_ANSWERS)).toBe(false);
      expect(isAnswered(step, complete)).toBe(true);
    }
  });

  it('counts "No limit" as an answer to the time question', () => {
    expect(isAnswered('time', { ...complete, minutes: null })).toBe(true);
  });

  it('lets optional screens through empty', () => {
    for (const step of ['welcome', 'echo', 'equipment', 'limits', 'obstacles'] as const) {
      expect(isAnswered(step, EMPTY_ANSWERS)).toBe(true);
    }
  });
});

describe('toProfileWrite', () => {
  it('maps every answer to the profile', () => {
    const answers: Answers = {
      ...complete,
      history: 'six_months_to_two_years',
      location: 'home',
      equipment: ['dumbbells', 'pull_up_bar'],
      quiet: true,
      limits: ['knees'],
      obstacles: ['no_time', 'get_bored'],
    };

    expect(toProfileWrite(answers)).toEqual({
      goal: 'build_muscle',
      level: 'some_experience',
      location: 'home',
      equipment: ['dumbbells', 'pull_up_bar'],
      women_home_track: true,
      days_per_week: 3,
      minutes_per_session: 45,
      limits: ['knees'],
      obstacles: ['no_time', 'get_bored'],
    });
  });

  it.each([
    ['never_or_on_and_off', 'beginner'],
    ['six_months_to_two_years', 'some_experience'],
    ['two_years_plus', 'experienced'],
  ] as const)('sets the level from training history: %s', (history, level) => {
    expect(toProfileWrite({ ...complete, history }).level).toBe(level);
  });

  it('sends "No limit" as null', () => {
    expect(toProfileWrite({ ...complete, minutes: null }).minutes_per_session).toBeNull();
  });

  it('never sends home-only answers for the gym', () => {
    const odd: Answers = { ...complete, location: 'gym', equipment: ['dumbbells'], quiet: true };

    const profile = toProfileWrite(odd);

    expect(profile.equipment).toEqual([]);
    expect(profile.women_home_track).toBe(false);
  });

  it('refuses incomplete answers', () => {
    expect(() => toProfileWrite({ ...complete, minutes: undefined })).toThrow(
      IncompleteAnswersError,
    );
    expect(() => toProfileWrite({ ...complete, goal: undefined })).toThrow(IncompleteAnswersError);
  });
});

describe('chooseLocation', () => {
  it('clears home answers when switching to the gym', () => {
    const home = { ...EMPTY_ANSWERS, location: 'home' as const, equipment: ['dumbbells' as const], quiet: true };

    expect(chooseLocation(home, 'gym')).toMatchObject({ location: 'gym', equipment: [], quiet: false });
    expect(chooseLocation(home, 'home')).toMatchObject({ equipment: ['dumbbells'], quiet: true });
  });
});

describe('small helpers', () => {
  it('toggles a value in and out', () => {
    expect(toggle(['knees'], 'back')).toEqual(['knees', 'back']);
    expect(toggle(['knees', 'back'], 'knees')).toEqual(['back']);
  });

  it('tidies the optional name', () => {
    expect(displayName({ ...EMPTY_ANSWERS, name: '  Shawaiz ' })).toBe('Shawaiz');
    expect(displayName({ ...EMPTY_ANSWERS, name: '   ' })).toBeNull();
    expect(displayName({ ...EMPTY_ANSWERS, name: 'x'.repeat(80) })).toHaveLength(50);
  });

  it('has an echo for every goal, with the honest fat-loss note', () => {
    for (const goal of GOALS) expect(echoFor(goal.value)).not.toBe('');
    expect(echoFor('lose_fat')).toMatch(/eating less than you burn/);
  });
});

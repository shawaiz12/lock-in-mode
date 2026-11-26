import {
  type Answers,
  chooseLocation,
  cleanName,
  DAY_HINTS,
  DAYS,
  echoFor,
  EMPTY_ANSWERS,
  FLOW_LENGTH,
  GOALS,
  IncompleteAnswersError,
  isAnswered,
  needsButton,
  PACT_STEP,
  QUESTIONS,
  SAFETY_STEP,
  STEPS,
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

describe('the steps (ADR 0036)', () => {
  it('asks six questions, in the playbook order', () => {
    expect(STEPS).toEqual(['goal', 'history', 'where', 'days', 'time', 'limits']);
  });

  it('counts the safety list and the pact in the progress bar: 8 steps in all', () => {
    expect(FLOW_LENGTH).toBe(8);
    expect([SAFETY_STEP, PACT_STEP]).toEqual([7, 8]);
  });

  it('says why it asks, on every question', () => {
    for (const step of STEPS) {
      expect(QUESTIONS[step].title).not.toBe('');
      expect(QUESTIONS[step].why).not.toBe('');
    }
  });

  it('needs a button only where one tap can’t be the answer', () => {
    expect(needsButton('where', { ...EMPTY_ANSWERS, location: 'home' })).toBe(true);
    expect(needsButton('where', { ...EMPTY_ANSWERS, location: 'gym' })).toBe(false);
    expect(needsButton('limits', { ...EMPTY_ANSWERS, limits: ['knees'] })).toBe(true);
    expect(needsButton('limits', EMPTY_ANSWERS)).toBe(false); // "None" moves on
    for (const step of ['goal', 'history', 'days', 'time'] as const) {
      expect(needsButton(step, EMPTY_ANSWERS)).toBe(false);
    }
  });

  it('never promises a split from the number of days', () => {
    for (const days of DAYS) expect(DAY_HINTS[days]).not.toMatch(/split|push|pull|legs|upper|lower|full body/i);
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

  it('lets "no limits" through empty', () => {
    expect(isAnswered('limits', EMPTY_ANSWERS)).toBe(true);
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
      obstacles: [], // not asked any more (ADR 0036)
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

  it('tidies the optional name (Settings)', () => {
    expect(cleanName('  Shawaiz ')).toBe('Shawaiz');
    expect(cleanName('   ')).toBeNull();
    expect(cleanName('x'.repeat(80))).toHaveLength(50);
  });

  it('has an echo for every goal, with the honest fat-loss note', () => {
    for (const goal of GOALS) expect(echoFor(goal.value)).not.toBe('');
    expect(echoFor('lose_fat')).toMatch(/eating less than you burn/);
  });
});

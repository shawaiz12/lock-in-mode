import { QUESTIONS, screenFrom } from './answers';

describe('the safety list', () => {
  it('asks all four questions the server needs', () => {
    expect(QUESTIONS.map((q) => q.key).sort()).toEqual(
      ['chest_pain_when_active', 'heart_condition', 'pregnant', 'recent_surgery_or_injury'].sort(),
    );
  });

  it('"None of these" sends four noes', () => {
    expect(screenFrom([])).toEqual({
      heart_condition: false,
      chest_pain_when_active: false,
      pregnant: false,
      recent_surgery_or_injury: false,
    });
  });

  it('a ticked item is a yes, the rest stay no', () => {
    expect(screenFrom(['pregnant'])).toEqual({
      heart_condition: false,
      chest_pain_when_active: false,
      pregnant: true,
      recent_surgery_or_injury: false,
    });
    expect(Object.values(screenFrom(QUESTIONS.map((q) => q.key)))).toEqual([true, true, true, true]);
  });
});

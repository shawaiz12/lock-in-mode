import { anyYes, completeAnswers, QUESTIONS } from './answers';

const allNo = {
  heart_condition: false,
  chest_pain_when_active: false,
  pregnant: false,
  recent_surgery_or_injury: false,
};

describe('completeAnswers', () => {
  it('needs every question answered', () => {
    expect(completeAnswers({})).toBeNull();
    expect(completeAnswers({ ...allNo, pregnant: undefined })).toBeNull();
  });

  it('sends each answer to its own field', () => {
    for (const question of QUESTIONS) {
      const answers = { ...allNo, [question.key]: true };

      expect(completeAnswers(answers)).toEqual(answers);
    }
  });
});

describe('anyYes', () => {
  it('spots a single yes', () => {
    expect(anyYes(allNo)).toBe(false);
    expect(anyYes({ ...allNo, chest_pain_when_active: true })).toBe(true);
  });
});

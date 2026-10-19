import type { AnswerValue } from './answerQueue';

export interface LocalAnswer extends AnswerValue { dirty: boolean }

export function acknowledgeChoice(current: LocalAnswer, sent: AnswerValue,
  acknowledgedRevision: number, hasNewerChoice: boolean): LocalAnswer {
  return hasNewerChoice
    ? { ...current, revision: acknowledgedRevision, dirty: true }
    : { ...sent, revision: acknowledgedRevision, dirty: false };
}

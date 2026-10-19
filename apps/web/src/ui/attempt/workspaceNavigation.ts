import type { Attempt, AttemptQuestion } from '../../domain/types';
import { stageLock, isCurrentPhaseQuestion } from './stageLock.ts';

export function questionEligible(attempt: Pick<Attempt, 'timing' | 'status' | 'mode'>, question: AttemptQuestion): boolean {
  return isCurrentPhaseQuestion({ phaseQuestionIds: attempt.timing.phase_question_ids, questionId: question.id }) &&
    stageLock({ questionPart: question.part, questionId: question.id, section: question.section,
      phase: attempt.timing.phase, phaseQuestionIds: attempt.timing.phase_question_ids,
      status: attempt.status, isPaused: attempt.timing.is_paused, mode: attempt.mode }).editable;
}

export function nextEligibleIndex(attempt: Attempt, currentIndex: number): number | null {
  const current = attempt.questions[currentIndex];
  if (!current || !questionEligible(attempt, current)) return null;
  for (let index = currentIndex + 1; index < attempt.questions.length; index++) {
    if (questionEligible(attempt, attempt.questions[index])) return index;
  }
  return null;
}

export function activityTarget(attempt: Attempt, index: number, answering: boolean, visible: boolean, owner: boolean): string | null {
  const question = attempt.questions[index];
  return owner && answering && visible && question && questionEligible(attempt, question) ? question.id : null;
}

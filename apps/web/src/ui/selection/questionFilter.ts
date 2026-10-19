import type { AttemptMode, AttemptScope, QuestionFilter } from '../../domain/types';

export function usesCompleteExamScope(mode: AttemptMode, scope: AttemptScope): boolean {
  return mode === 'exam' && (scope === 'full' || scope === 'listening' || scope === 'reading');
}

export function effectiveQuestionFilter(mode: AttemptMode, scope: AttemptScope, selected: QuestionFilter): QuestionFilter {
  return usesCompleteExamScope(mode, scope) ? 'all' : selected;
}

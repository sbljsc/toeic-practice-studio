import type { AttemptReport } from '../../domain/types';
import type { SelectionPrefill } from '../selection';

// This library has the same verified 200-item layout in each of its ten tests.
const PART_COUNTS: Record<number, number> = { 1: 6, 2: 25, 3: 39, 4: 30, 5: 30, 6: 16, 7: 54 };

export function retakeSelection(report: AttemptReport, plannedSeconds: number | null): SelectionPrefill {
  const original = report.attempt;
  const parts = original.scope === 'full' ? [1, 2, 3, 4, 5, 6, 7]
    : original.scope === 'listening' ? [1, 2, 3, 4]
    : original.scope === 'reading' ? [5, 6, 7] : original.parts;
  const complete = parts.length > 0 && original.exam_ids.every((examId) =>
    parts.every((part) => new Set(report.questions.filter((q) => q.exam_id === examId && q.part === part)
      .map((q) => q.id)).size === PART_COUNTS[part]));
  const custom = original.scope === 'custom' || !complete;
  const seconds = original.timer_config?.duration_seconds ?? plannedSeconds;
  return {
    examIds: original.exam_ids,
    scope: custom ? 'custom' : original.scope,
    parts: custom ? [] : original.parts,
    mode: original.mode,
    questionFilter: 'all',
    timerKind: original.timer_config?.kind ?? (original.mode === 'exam' ? 'countdown' : 'none'),
    timerMinutes: seconds && seconds > 0 ? seconds / 60 : 75,
    groupIds: custom ? report.groups.map((group) => group.id) : undefined,
  };
}

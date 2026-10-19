import type { Attempt, AttemptReport } from '../../domain/types.ts';

/** Closed report projection for the shared workspace; no live answer/timer writes. */
export function reviewWorkspace(report: AttemptReport, snapshot?: Attempt | null): Attempt {
  const matching = snapshot?.id === report.attempt.id ? snapshot : undefined;
  return {
    ...report.attempt,
    created_at: report.attempt.created_at ?? '',
    status: report.attempt.status === 'expired' ? 'expired' : 'submitted',
    current_index: 0,
    question_count: report.questions.length,
    questions: report.questions,
    groups: report.groups,
    owner_tab_id: null,
    answers: Object.fromEntries(report.questions.map((question) => [question.id, {
      option_id: question.selected_option_id,
      flagged: matching?.answers[question.id]?.flagged ?? false,
      visited: matching?.answers[question.id]?.visited ?? question.selected_option_id !== null,
      revision: matching?.answers[question.id]?.revision ?? 0,
    }])),
    timing: { kind: 'none', phase: 'finished', remaining_ms: null, elapsed_ms: 0,
      server_time_ms: 0, deadline_at_ms: null, can_pause: false, is_paused: false,
      integrity: report.attempt.integrity ?? 'valid', phase_question_ids: [] },
    audio_queue: matching?.audio_queue ?? [],
    audio_elapsed_ms: 0,
    activity: report.activity,
  };
}

export function reviewFocusIndex(report: AttemptReport, questionId?: string | null): number {
  return Math.max(0, report.questions.findIndex((question) => question.id === questionId));
}

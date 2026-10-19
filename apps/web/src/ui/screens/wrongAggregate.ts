// A wrong answer stays "unresolved" until the learner answers that canonical
// question correctly in a LATER graded attempt. Unanswered questions are not
// wrong answers, so they are excluded from the wrong book entirely.

import type { AttemptReport, ReportQuestion } from '../../domain/types';

export interface WrongEntry {
  question: ReportQuestion;
  /** The most recent graded attempt that still shows this question as wrong. */
  attemptId: string;
  attemptTitle: string;
  /** How many graded attempts have shown this question wrong. */
  wrongCount: number;
  /** How many later attempts answered it correctly. */
  fixedCount: number;
  lastSeenAt: string;
}

interface AttemptMeta {
  id: string;
  title: string;
  created_at: string;
}

export function aggregateWrongAnswers(
  reports: AttemptReport[],
  meta: Record<string, AttemptMeta>,
): WrongEntry[] {
  interface Trace {
    question: ReportQuestion;
    attemptId: string;
    at: number;
  }
  const byCanonical = new Map<string, Trace[]>();

  for (const report of reports) {
    // An interrupted run is not a reliable grade, so it neither adds nor clears
    // wrong answers.
    if (report.attempt.integrity !== undefined && report.attempt.integrity !== 'valid') continue;
    const info = meta[report.attempt.id];
    // Several rounds can remain open together. A result takes effect when
    // submitted, even when that round was created before another one.
    const completedAt = report.attempt.closed_at || info?.created_at || '';
    const at = Date.parse(completedAt) || 0;
    for (const question of report.questions) {
      if (question.result === 'unanswered') continue;
      const list = byCanonical.get(question.canonical_id) ?? [];
      list.push({ question, attemptId: report.attempt.id, at });
      byCanonical.set(question.canonical_id, list);
    }
  }

  const entries: WrongEntry[] = [];
  for (const [canonicalId, traces] of byCanonical) {
    traces.sort((a, b) => a.at - b.at);
    const last = traces[traces.length - 1];
    // Only a later CORRECT answer resolves a question. A later unanswered or
    // skipped attempt must not erase a prior unresolved wrong answer.
    if (last.question.result === 'correct') continue;
    const latestWrong = [...traces].reverse().find((item) => item.question.result === 'wrong');
    if (!latestWrong) continue;
    const wrongCount = traces.filter((item) => item.question.result === 'wrong').length;
    const fixedCount = traces.filter((item) => item.question.result === 'correct').length;
    entries.push({
      question: latestWrong.question,
      attemptId: latestWrong.attemptId,
      attemptTitle: meta[latestWrong.attemptId]?.title ?? '',
      wrongCount,
      fixedCount,
      lastSeenAt: meta[latestWrong.attemptId]?.created_at ?? '',
    });
    void canonicalId;
  }

  entries.sort((a, b) => (a.question.part - b.question.part) || (a.question.number - b.question.number));
  return entries;
}

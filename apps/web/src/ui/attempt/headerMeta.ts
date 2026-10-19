// Pure label helpers for the workspace header and preflight card. Kept
// separate so the "未开始" state and source wording are regression-tested
// without rendering.

import type { Attempt, AttemptScope, AttemptMode } from '../../domain/types';

export const PHASE_LABEL: Record<string, string> = {
  listening: '听力',
  reading: '阅读',
  practice: '练习',
  finished: '已结束',
};

export const SCOPE_LABEL_TEXT: Record<AttemptScope, string> = {
  full: '完整模拟',
  listening: '仅听力',
  reading: '仅阅读',
  part: 'Part 专项',
  custom: '自选题组',
};

export const MODE_LABEL_TEXT: Record<AttemptMode, string> = {
  exam: '模拟',
  practice: '练习',
};

/** "练习 · 练习" reads badly; collapse a duplicated scope/mode pair. */
export function headerContext(attempt: {
  scope: AttemptScope;
  mode: AttemptMode;
  phase: string;
  status: string;
}): string {
  if (attempt.status === 'ready') return '未开始';
  const phase = PHASE_LABEL[attempt.phase] ?? '阶段';
  const scope = SCOPE_LABEL_TEXT[attempt.scope];
  const mode = MODE_LABEL_TEXT[attempt.mode];
  if (mode === '练习') {
    // Practice scope already says 练习; the phase adds the section instead.
    return phase === '练习' ? scope : `${scope} · ${phase}`;
  }
  if (attempt.phase === 'practice') return `${scope} · ${mode}`;
  return phase === mode ? `${scope} · ${mode}` : `${scope} · ${mode} · ${phase}`;
}

/** Turn an internal exam id such as "test-01" into "TEST 01". */
export function prettyExamId(examId: string): string {
  const match = /^test-(\d+)$/i.exec(examId.trim());
  if (!match) return examId;
  return `TEST ${match[1].replace(/^0+(?=\d)/, '').padStart(2, '0')}`;
}

export function prettyExamIds(attempt: Pick<Attempt, 'exam_ids'>): string {
  if (attempt.exam_ids.length === 0) return '—';
  if (attempt.exam_ids.includes('pool')) return '随机题库';
  return attempt.exam_ids.map(prettyExamId).join('、');
}

const PLANNED_PREFIX = 'toeic.planned.';

/**
 * Read the locally remembered creation budget for a not-yet-started attempt.
 * This is display-only and never feeds the running clock or grading.
 */
export function readPlannedSeconds(attemptId: string): number | null {
  try {
    const raw = window.sessionStorage.getItem(PLANNED_PREFIX + attemptId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { seconds?: number | null };
    return typeof parsed.seconds === 'number' ? parsed.seconds : null;
  } catch {
    return null;
  }
}

/**
 * Duration shown on the preflight card. For a ready attempt this is the
 * planned budget, not a running clock: never derived from a decrementing
 * counter, so it cannot drift from the server deadline.
 */
export function plannedDurationText(input: {
  kind: 'countdown' | 'countup' | 'none';
  remainingMs: number | null;
  phase: string;
  /** True before the attempt has started; the deadline is not armed yet. */
  ready?: boolean;
  /** The duration the learner chose when creating the attempt, if known. */
  plannedSeconds?: number | null;
}): string {
  if (input.kind === 'none') return '不计时';
  if (input.kind === 'countup') return '正计时';
  if (input.ready) {
    // The server arms the deadline at start, so nothing is counting yet. Show
    // the rule that will apply instead of an invented remaining time.
    if (input.plannedSeconds && input.plannedSeconds > 0) {
      return `${Math.round(input.plannedSeconds / 60)} 分钟（开始后计时）`;
    }
    return '开始后计时';
  }
  if (input.remainingMs === null) return '倒计时';
  const totalSeconds = Math.round(input.remainingMs / 1000);
  if (totalSeconds <= 0) return '倒计时';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  if (minutes === 0) return `${seconds} 秒`;
  if (seconds > 0) return `${minutes} 分 ${seconds} 秒`;
  return `${minutes} 分钟`;
}

/** The header must read "未开始" until the attempt actually starts. */
export function headerTimerText(input: {
  status: string;
  kind: 'countdown' | 'countup' | 'none';
  display: string;
}): string {
  if (input.status === 'ready') return '未开始';
  return input.display;
}

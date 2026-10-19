// Preflight duration respects the frozen attempt snapshot. Random-pool strict
// exams use their persisted 45/75/120-minute schedule; legacy strict exams use
// their frozen audio queue because old timer_config may only reflect a request.

import type { AudioQueueItem, AttemptScope, TimerConfig, TimerKind } from '../../domain/types';

export const READING_EXAM_SECONDS = 75 * 60;

export interface ExamDuration {
  /** Primary line shown on the preflight card. */
  text: string;
  /** Listening and reading components, when the schedule has both. */
  listeningSeconds?: number;
  readingSeconds?: number;
}

export function totalQueueSeconds(queue: AudioQueueItem[]): number {
  return queue.reduce((sum, item) => sum + Math.max(0, item.end_seconds - item.start_seconds), 0);
}

export function formatDurationParts(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function examDuration(input: {
  scope: AttemptScope;
  mode: 'exam' | 'practice';
  audioQueue: AudioQueueItem[];
  isPoolAttempt?: boolean;
  timerConfig?: TimerConfig;
  timerKind?: TimerKind;
  plannedSeconds: number | null;
}): ExamDuration {
  const isScheduledExam = input.mode === 'exam' && (input.scope === 'full' || input.scope === 'listening');

  // Reading mocks always use the fixed 75-minute section budget.
  if (input.mode === 'exam' && input.scope === 'reading') {
    return { text: `${formatDurationMinutes(READING_EXAM_SECONDS)}（开始后计时）`, readingSeconds: READING_EXAM_SECONDS };
  }

  // The attempt snapshot is authoritative. A local creation hint may belong to
  // a different selection, and the media queue can be shorter than the timed
  // listening phase in a random-pool exam.
  const useTimerSnapshot = !isScheduledExam || input.isPoolAttempt === true;
  if (input.timerConfig && useTimerSnapshot) {
    if (input.timerConfig.kind === 'none') return { text: '不计时' };
    if (input.timerConfig.kind === 'countup') return { text: '正计时' };
    const budgetSeconds = input.timerConfig.duration_seconds;
    if (typeof budgetSeconds !== 'number' || !Number.isFinite(budgetSeconds) || budgetSeconds <= 0) {
      return { text: '开始后计时' };
    }
    if (input.mode === 'exam' && input.scope === 'listening') {
      return { text: `听力 ${formatDurationParts(budgetSeconds)}（开始后计时）`, listeningSeconds: budgetSeconds };
    }
    if (input.mode === 'exam' && input.scope === 'full') {
      const readingSeconds = READING_EXAM_SECONDS;
      const listeningSeconds = Math.max(0, budgetSeconds - readingSeconds);
      return {
        text: `听力 ${formatDurationParts(listeningSeconds)} + 阅读 ${formatDurationParts(readingSeconds)}（合计 ${formatDurationParts(budgetSeconds)}）`,
        listeningSeconds,
        readingSeconds,
      };
    }
    return { text: formatDurationMinutes(budgetSeconds) + '（开始后计时）' };
  }

  if (!isScheduledExam && input.timerKind === 'none') return { text: '不计时' };
  if (!isScheduledExam && input.timerKind === 'countup') return { text: '正计时' };

  if (!isScheduledExam) {
    // Older attempts without a server timer snapshot may still have a local hint.
    if (input.plannedSeconds && input.plannedSeconds > 0) {
      return { text: `${formatDurationMinutes(input.plannedSeconds)}（开始后计时）` };
    }
    return { text: '开始后计时' };
  }

  const listeningSeconds = totalQueueSeconds(input.audioQueue);
  if (input.scope === 'listening') {
    return {
      text: `听力 ${formatDurationParts(listeningSeconds)}（开始后计时）`,
      listeningSeconds,
    };
  }

  const readingSeconds = READING_EXAM_SECONDS;
  const totalSeconds = listeningSeconds + readingSeconds;
  return {
    text: `听力 ${formatDurationParts(listeningSeconds)} + 阅读 ${formatDurationParts(readingSeconds)}（合计 ${formatDurationParts(totalSeconds)}）`,
    listeningSeconds,
    readingSeconds,
  };
}

function formatDurationMinutes(seconds: number): string {
  const minutes = seconds / 60;
  return Number.isInteger(minutes) ? `${minutes} 分钟` : `${formatDurationParts(seconds)}`;
}

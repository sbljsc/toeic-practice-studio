import type { AttemptScope, AttemptMode, TimerKind, VocabStatus, ReviewCause } from './types';

export const SCOPE_LABEL: Record<AttemptScope, string> = {
  full: '完整模拟',
  listening: '仅听力',
  reading: '仅阅读',
  part: 'Part 专项',
  custom: '自选题组',
};

export const MODE_LABEL: Record<AttemptMode, string> = {
  exam: '模拟',
  practice: '练习',
};

export const TIMER_LABEL: Record<TimerKind, string> = {
  countdown: '倒计时',
  countup: '正计时',
  none: '不计时',
};

export const VOCAB_STATUS_LABEL: Record<VocabStatus, string> = {
  candidate: '候选',
  concentrated: '集中错误',
  must_learn: '必背',
  mastered: '已掌握',
};

export const CAUSE_LABEL: Record<ReviewCause, string> = {
  meaning: '词义不懂',
  listening: '认识但没听出',
  grammar: '语法',
  paraphrase: '同义替换/推断',
  time: '时间不足',
  careless: '粗心',
  material: '材料问题',
  unknown: '暂不确定',
};

export const CAUSES: ReviewCause[] = [
  'meaning',
  'listening',
  'grammar',
  'paraphrase',
  'time',
  'careless',
  'material',
  'unknown',
];

export const VOCAB_CAUSES: ReviewCause[] = ['meaning', 'listening'];

export const PART_LABEL: Record<number, string> = {
  1: 'Part 1 照片描述',
  2: 'Part 2 应答',
  3: 'Part 3 对话',
  4: 'Part 4 独白',
  5: 'Part 5 短句填空',
  6: 'Part 6 篇章填空',
  7: 'Part 7 阅读理解',
};

export function shortPart(part: number): string {
  return `Part ${part}`;
}

export function sectionLabel(section: 'listening' | 'reading'): string {
  return section === 'listening' ? '听力' : '阅读';
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(1)}%`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function practiceTitle(scope: AttemptScope, createdAt: string): string {
  return `${SCOPE_LABEL[scope]} · ${formatDateTime(createdAt)}`;
}

export function newMutationId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

// Manifest source ids are the registered asset ids for the two copied PDFs
// (docs/library-contract.md -> sources:[{id,path,title}]). Verified against
// .data/library/manifest.json: id "listening" and id "reading".
export function sourcePdfAssetId(section: 'listening' | 'reading'): string {
  return section === 'listening' ? 'listening' : 'reading';
}

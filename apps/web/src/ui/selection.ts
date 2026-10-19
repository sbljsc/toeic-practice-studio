import { useEffect, useState } from 'react';
import { api } from '../domain/http';
import type { ExamMeta, GroupMeta, Part } from '../domain/types';
import type { AttemptMode, AttemptScope, QuestionFilter, TimerKind } from '../domain/types';
import { defaultTimerMinutes, effectiveTimerKind, isTimerAllowed, restoreTimerMinutes, timerRule, timerMinutesAfterScopeChange, READING_EXAM_MINUTES, TIMER_DEFAULTS_VERSION } from './selection/timer';

export interface Selection {
  examIds: string[];
  scope: AttemptScope;
  parts: number[];
  mode: AttemptMode;
  timerKind: TimerKind;
  timerMinutes: number;
  questionFilter: QuestionFilter;
  groupIds: string[];
}

export const PARTS: Array<{ part: Part; section: 'listening' | 'reading'; label: string; hint: string }> = [
  { part: 1, section: 'listening', label: 'Part 1 照片描述', hint: '一图四选，6 题' },
  { part: 2, section: 'listening', label: 'Part 2 应答', hint: '一问三答，25 题' },
  { part: 3, section: 'listening', label: 'Part 3 对话', hint: '对话三题一组，39 题' },
  { part: 4, section: 'listening', label: 'Part 4 独白', hint: '独白三题一组，30 题' },
  { part: 5, section: 'reading', label: 'Part 5 短句填空', hint: '独立单题，30 题' },
  { part: 6, section: 'reading', label: 'Part 6 篇章填空', hint: '篇章四题一组，16 题' },
  { part: 7, section: 'reading', label: 'Part 7 阅读理解', hint: '单/双/三篇，54 题' },
];

export const SCOPES: Array<{ scope: AttemptScope; label: string; hint: string; parts?: Part[] }> = [
  { scope: 'full', label: '完整模拟', hint: '练习默认 120 分钟' },
  { scope: 'listening', label: '仅听力', hint: '练习默认 45 分钟' },
  { scope: 'reading', label: '仅阅读', hint: '练习默认 75 分钟' },
  { scope: 'part', label: 'Part 专项', hint: '按完整题组抽取' },
  { scope: 'custom', label: '自选题组', hint: '手动勾选题组' },
];

export const FILTERS: Array<{ filter: QuestionFilter; label: string }> = [
  { filter: 'all', label: '全部' },
  { filter: 'unanswered', label: '未做' },
  { filter: 'wrong', label: '错题' },
  { filter: 'bookmarked', label: '收藏' },
];

const TIMERS: Array<{ kind: TimerKind; label: string }> = [
  { kind: 'countdown', label: '倒计时' },
  { kind: 'countup', label: '正计时' },
  { kind: 'none', label: '不计时' },
];

const STORAGE_KEY = 'toeic.last-selection';

/** One-shot prefill used by "再练一遍" so a retake never inherits an
 *  unrelated last-used selection. Consumed once by PracticeHome. */
export const PREFILL_STORAGE_KEY = 'toeic.prefill-selection';

export interface SelectionPrefill {
  examIds: string[];
  scope: AttemptScope;
  parts: number[];
  mode: AttemptMode;
  questionFilter: QuestionFilter;
  timerKind: TimerKind;
  timerMinutes: number;
  groupIds?: string[];
}

export function storePrefill(prefill: SelectionPrefill): void {
  try {
    window.sessionStorage.setItem(PREFILL_STORAGE_KEY, JSON.stringify(prefill));
  } catch {
    // Without storage the retake simply falls back to the last-used selection.
  }
}

export function takePrefill(): SelectionPrefill | null {
  try {
    const raw = window.sessionStorage.getItem(PREFILL_STORAGE_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(PREFILL_STORAGE_KEY);
    return JSON.parse(raw) as SelectionPrefill;
  } catch {
    return null;
  }
}

interface StoredSelection {
  timerDefaultsVersion?: number;
  examIds: string[];
  scope: AttemptScope;
  parts: number[];
  mode: AttemptMode;
  timerKind: TimerKind;
  timerMinutes: number;
  questionFilter: QuestionFilter;
}

export function defaultSelection(): Selection {
  return {
    examIds: [],
    scope: 'reading',
    parts: [],
    mode: 'practice',
    timerKind: 'countdown',
    timerMinutes: defaultTimerMinutes('reading'),
    questionFilter: 'all',
    groupIds: [],
  };
}

export function useStoredSelection(): [Selection, (next: Selection) => void] {
  const [selection, setSelection] = useState<Selection>(() => {
    const base = defaultSelection();
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return base;
      const parsed = JSON.parse(raw) as Partial<StoredSelection>;
      return {
        ...base,
        examIds: Array.isArray(parsed.examIds) ? parsed.examIds : base.examIds,
        scope: parsed.scope ?? base.scope,
        parts: Array.isArray(parsed.parts) ? parsed.parts : base.parts,
        mode: parsed.mode ?? base.mode,
        timerKind: parsed.timerKind ?? base.timerKind,
        timerMinutes: restoreTimerMinutes(parsed.scope ?? base.scope, parsed.timerMinutes, parsed.timerDefaultsVersion),
        questionFilter: parsed.questionFilter ?? base.questionFilter,
      };
    } catch {
      return base;
    }
  });

  const update = (next: Selection) => {
    setSelection(next);
    const stored: StoredSelection = {
      timerDefaultsVersion: TIMER_DEFAULTS_VERSION,
      examIds: next.examIds,
      scope: next.scope,
      parts: next.parts,
      mode: next.mode,
      timerKind: next.timerKind,
      timerMinutes: next.timerMinutes,
      questionFilter: next.questionFilter,
    };
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    } catch {
      // A blocked localStorage only costs us the "remember last choice" convenience.
    }
  };

  return [selection, update];
}

export function scopeSection(scope: AttemptScope): 'listening' | 'reading' | 'both' {
  if (scope === 'listening') return 'listening';
  if (scope === 'reading') return 'reading';
  return 'both';
}

export function partsForScope(selection: Selection): Part[] {
  switch (selection.scope) {
    case 'full':
      return [1, 2, 3, 4, 5, 6, 7];
    case 'listening':
      return [1, 2, 3, 4];
    case 'reading':
      return [5, 6, 7];
    case 'part':
    case 'custom':
      return selection.parts as Part[];
    default:
      return [];
  }
}

export function sectionOfPart(part: number): 'listening' | 'reading' {
  return part <= 4 ? 'listening' : 'reading';
}

export function isScopeReady(
  selection: Selection,
  exams: ExamMeta[],
): { ready: boolean; reason: string | null } {
  if (selection.examIds.length === 0) {
    return { ready: false, reason: '请至少选择一套题。' };
  }
  if (selection.scope === 'full' && selection.examIds.length !== 1) {
    return { ready: false, reason: '完整模拟限定单套题，请取消多余套题。' };
  }
  const parts = partsForScope(selection);
  if (selection.scope !== 'custom' && parts.length === 0) {
    return { ready: false, reason: '请至少选择一个 Part。' };
  }
  const chosen = exams.filter((exam) => selection.examIds.includes(exam.id));
  if (chosen.length !== selection.examIds.length) {
    return { ready: false, reason: '所选套题已不在当前题库中。' };
  }
  for (const exam of chosen) {
    if (selection.scope === 'full') {
      if (!exam.ready) {
        return { ready: false, reason: `${exam.title} 尚未取得完整模拟资格：${exam.parts.find((p) => !p.ready)?.reason ?? '素材待核验'}` };
      }
      continue;
    }
    for (const part of parts) {
      const meta = exam.parts.find((item) => item.part === part);
      if (!meta) {
        return { ready: false, reason: `${exam.title} 不含 Part ${part}。` };
      }
      if (!meta.ready) {
        return { ready: false, reason: `${exam.title} Part ${part}：${meta.reason ?? '素材待核验'}` };
      }
    }
  }
  // A stale stored timer must never produce a request the exam cannot honor.
  const kind = effectiveTimerKind(selection.mode, selection.scope, selection.timerKind);
  if (!isTimerAllowed(selection.mode, selection.scope, kind)) {
    return { ready: false, reason: '当前范围不支持所选计时方式，请重新选择。' };
  }
  if (kind === 'countdown' && timerRule(selection.mode, selection.scope).forcedMinutes == null && selection.timerMinutes <= 0) {
    return { ready: false, reason: '倒计时需要大于 0 的分钟数。' };
  }
  return { ready: true, reason: null };
}

export function filterGroups(groups: GroupMeta[], parts: number[], _filter: QuestionFilter): GroupMeta[] {
  let result = groups;
  if (parts.length > 0) {
    result = result.filter((group) => parts.includes(group.part));
  }
  return result;
}

export function timerLabelFor(selection: Selection): string {
  const rule = timerRule(selection.mode, selection.scope);
  if (rule.forced === 'countdown') {
    if (rule.forcedMinutes) return `${rule.forcedMinutes} 分钟`;
    return '按考试日程';
  }
  const kind = effectiveTimerKind(selection.mode, selection.scope, selection.timerKind);
  if (kind === 'countdown') return `${selection.timerMinutes} 分钟`;
  if (kind === 'countup') return '正计时';
  return '不计时';
}

export { TIMERS };

export { timerRule, effectiveTimerKind, isTimerAllowed, timerMinutesAfterScopeChange, READING_EXAM_MINUTES };

export interface GroupCatalogEntry extends GroupMeta {
  examId: string;
  examTitle: string;
}

/**
 * Loads groups for every chosen exam. Question and group ids are unique across
 * tests per the contract, so multi-exam custom selection stays unambiguous.
 */
export function useGroupCatalog(
  examIds: string[],
  examTitleById: Record<string, string>,
) {
  const [groups, setGroups] = useState<GroupMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = examIds.join(',');

  useEffect(() => {
    if (examIds.length === 0) {
      setGroups([]);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all(
      examIds.map(async (examId) => {
        const response = await api.groups(examId);
        return response.groups.map<GroupCatalogEntry>((group) => ({
          ...group,
          examId,
          examTitle: examTitleById[examId] ?? examId,
        }));
      }),
    )
      .then((perExam) => {
        if (!active) return;
        setGroups(perExam.flat());
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setGroups([]);
        setError(cause instanceof Error ? cause.message : '题组清单读取失败。');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { groups, loading, error };
}

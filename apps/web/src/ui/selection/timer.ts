// Single source of truth for which timers a mode/scope may use. The UI must
// never show a disabled "不计时" button next to a countdown the exam requires,
// and must not send a timer kind the exam scope cannot honor.

export type TimerKind = 'countdown' | 'countup' | 'none';
export type AttemptMode = 'exam' | 'practice';
export type AttemptScope = 'full' | 'listening' | 'reading' | 'part' | 'custom';
export type TimerMinutesByScope = Partial<Record<AttemptScope, number>>;

export interface TimerRule {
  /** Timer kinds the learner may pick. */
  allowed: TimerKind[];
  /** The kind actually sent, when the UI must force one. */
  forced: TimerKind | null;
  /** Minutes for a forced countdown, if the exam dictates one. */
  forcedMinutes?: number;
  note: string | null;
}

export const READING_EXAM_MINUTES = 75;
export const TIMER_DEFAULTS_VERSION = 1;

export function defaultTimerMinutes(scope: AttemptScope): number {
  if (scope === 'full') return 120;
  if (scope === 'reading') return READING_EXAM_MINUTES;
  return 45;
}

export function timerMinutesAfterScopeChange(
  currentScope: AttemptScope,
  nextScope: AttemptScope,
  currentMinutes: number,
  savedMinutes: TimerMinutesByScope = {},
): number {
  if (currentScope === nextScope) return currentMinutes;
  return validTimerMinutes(savedMinutes[nextScope]) ?? defaultTimerMinutes(nextScope);
}

export function validTimerMinutes(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 1 && value <= 300
    ? value
    : undefined;
}

export function timerMinutesAfterEdit(
  scope: AttemptScope,
  minutes: unknown,
  savedMinutes: TimerMinutesByScope,
): TimerMinutesByScope {
  const value = validTimerMinutes(minutes);
  return value === undefined ? savedMinutes : { ...savedMinutes, [scope]: value };
}

/** Older selections reused one preset across scopes. Migrate those presets
 * once; arbitrary custom budgets and all newly saved choices stay intact. */
export function restoreTimerMinutes(
  scope: AttemptScope,
  storedMinutes: unknown,
  defaultsVersion: unknown,
): number {
  if (typeof storedMinutes !== 'number') return defaultTimerMinutes(scope);
  if (defaultsVersion == null && ['full', 'listening', 'reading'].includes(scope)
      && [45, 75, 120].includes(storedMinutes)) {
    return defaultTimerMinutes(scope);
  }
  return storedMinutes;
}

export function timerRule(mode: AttemptMode, scope: AttemptScope): TimerRule {
  if (mode !== 'exam') {
    return {
      allowed: ['countdown', 'countup', 'none'],
      forced: null,
      note: null,
    };
  }
  // A full mock is scheduled by the server: listening media duration, then the
  // reading block. The client does not pick a total.
  if (scope === 'full') {
    return {
      allowed: ['countdown'],
      forced: 'countdown',
      note: '完整模拟按考试日程进行：先听力，再阅读 75 分钟。',
    };
  }
  // Listening-only and reading-only mocks are timed sections, not free practice.
  if (scope === 'reading') {
    return {
      allowed: ['countdown'],
      forced: 'countdown',
      forcedMinutes: READING_EXAM_MINUTES,
      note: '仅阅读模拟固定 75 分钟。',
    };
  }
  if (scope === 'listening') {
    return {
      allowed: ['countdown'],
      forced: 'countdown',
      note: '仅听力模拟按教材音轨的实际时长计时。',
    };
  }
  // Part / custom mocks may use any personal timing, including none.
  return {
    allowed: ['countdown', 'countup', 'none'],
    forced: null,
    note: null,
  };
}

export function isTimerAllowed(mode: AttemptMode, scope: AttemptScope, kind: TimerKind): boolean {
  return timerRule(mode, scope).allowed.includes(kind);
}

/** The timer kind to actually send, honoring any exam-forced value. */
export function effectiveTimerKind(mode: AttemptMode, scope: AttemptScope, kind: TimerKind): TimerKind {
  const rule = timerRule(mode, scope);
  if (rule.forced) return rule.forced;
  return rule.allowed.includes(kind) ? kind : rule.allowed[0];
}

import { useEffect, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import type { AttemptMode, AttemptScope, CreateAttemptRequest, SelectionPreference, QuestionPoolCatalog, TimerKind } from '../../domain/types';
import { practiceTitle, SCOPE_LABEL, MODE_LABEL, TIMER_LABEL, PART_LABEL } from '../../domain/format';
import { Banner, EmptyBlock, Field, Loading } from '../components';
import { canAssembleTarget } from '../selection/poolSelection';
import { defaultTimerMinutes, timerMinutesAfterEdit, timerMinutesAfterScopeChange, validTimerMinutes, type TimerMinutesByScope } from '../selection/timer';

export interface AttemptSummaryView {
  id: string; title: string; scope: AttemptScope; mode: AttemptMode;
  status: 'ready' | 'running' | 'paused' | 'submitted' | 'expired';
  created_at: string; question_count: number; answered_count: number; parts: number[];
  exam_ids: string[]; summary?: { correct: number; wrong: number; unanswered: number; correct_percent: number };
}

interface Props {
  resumable: AttemptSummaryView[];
  onOpenAttempt: (id: string) => void;
  onStarted: (id: string) => void;
  onOpenHistory: () => void;
  reloadResumable: () => void;
}

const PARTS = [1, 2, 3, 4, 5, 6, 7];
const SCOPES: AttemptScope[] = ['full', 'listening', 'reading', 'part', 'custom'];
const PREFERENCES: Array<[SelectionPreference, string]> = [
  ['unanswered_first', '未做优先'], ['wrong_first', '错题优先'], ['answered_first', '已做优先'], ['random', '全随机'],
];
const TIMER_PREFERENCES_KEY = 'toeic.timer-minutes.v1';
const TIMER_SCOPES: AttemptScope[] = ['full', 'listening', 'reading', 'part', 'custom'];

function loadTimerMinutes(): TimerMinutesByScope {
  try {
    const stored = window.localStorage.getItem(TIMER_PREFERENCES_KEY);
    if (!stored) return {};
    const parsed: unknown = JSON.parse(stored);
    if (!parsed || typeof parsed !== 'object' || !('minutes' in parsed)) return {};
    const source = (parsed as { minutes?: unknown }).minutes;
    if (!source || typeof source !== 'object') return {};
    return Object.fromEntries(TIMER_SCOPES.flatMap((timerScope) => {
      const value = validTimerMinutes((source as Record<string, unknown>)[timerScope]);
      return value === undefined ? [] : [[timerScope, value]];
    }));
  } catch { return {}; }
}

function saveTimerMinutes(minutes: TimerMinutesByScope): void {
  try { window.localStorage.setItem(TIMER_PREFERENCES_KEY, JSON.stringify({ version: 1, minutes })); }
  catch { /* Timer preferences remain available for this visit. */ }
}

export function PracticeHome({ resumable, onOpenAttempt, onStarted, onOpenHistory, reloadResumable }: Props) {
  const [catalog, setCatalog] = useState<QuestionPoolCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState<AttemptScope>('full');
  const [mode, setMode] = useState<AttemptMode>('practice');
  const [preference, setPreference] = useState<SelectionPreference>('unanswered_first');
  const [timerKind, setTimerKind] = useState<TimerKind>('countdown');
  const [savedMinutes, setSavedMinutes] = useState<TimerMinutesByScope>(loadTimerMinutes);
  const [minutes, setMinutes] = useState(() => validTimerMinutes(savedMinutes.full) ?? defaultTimerMinutes('full'));
  const [part, setPart] = useState(1);
  const [target, setTarget] = useState(30);
  const [customCounts, setCustomCounts] = useState<Record<number, number>>({ 1: 6, 2: 25, 3: 39, 4: 30, 5: 30, 6: 16, 7: 54 });
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  function changeScope(nextScope: AttemptScope) {
    const updated = timerMinutesAfterEdit(scope, minutes, savedMinutes);
    setSavedMinutes(updated);
    saveTimerMinutes(updated);
    setMinutes(timerMinutesAfterScopeChange(scope, nextScope, minutes, updated));
    setScope(nextScope);
  }

  function changeMinutes(value: number) {
    setMinutes(value);
    const updated = timerMinutesAfterEdit(scope, value, savedMinutes);
    if (updated !== savedMinutes) {
      setSavedMinutes(updated);
      saveTimerMinutes(updated);
    }
  }

  async function loadCatalog() {
    setLoading(true); setCatalogError(null);
    try { setCatalog(await api.questionPool()); }
    catch (cause) { setCatalogError(cause instanceof Error ? cause.message : '题库读取失败。'); }
    finally { setLoading(false); }
  }
  useEffect(() => { void loadCatalog(); }, []);

  const partMeta = catalog?.parts.find((item) => item.part === part);
  const fixedTemplate = scope === 'full' ? catalog?.templates.full
    : scope === 'listening' ? catalog?.templates.listening : scope === 'reading' ? catalog?.templates.reading : undefined;
  const feasible = scope === 'part'
    ? Boolean(partMeta?.ready && canAssembleTarget(target, partMeta.group_sizes))
    : scope === 'custom' ? PARTS.some((p) => customCounts[p] > 0) && PARTS.every((p) => {
      const count = customCounts[p] ?? 0;
      if (count === 0) return true;
      const meta = catalog?.parts.find((item) => item.part === p);
      return Boolean(meta?.ready && canAssembleTarget(count, meta.group_sizes));
    }) : Boolean(catalog?.ready && fixedTemplate && Object.entries(fixedTemplate.part_counts).every(([p, n]) => {
      const meta = catalog.parts.find((item) => item.part === Number(p));
      return Boolean(meta?.ready && canAssembleTarget(n, meta.group_sizes));
    }));
  async function createAttempt() {
    if (!feasible || creating) return;
    const fixedExam = mode === 'exam' && ['full', 'listening', 'reading'].includes(scope);
    const timer: CreateAttemptRequest['timer'] = fixedExam
      ? { kind: 'countdown' as const, ...(scope === 'reading' ? { duration_seconds: 4500 } : {}) }
      : timerKind === 'countdown' ? { kind: timerKind, duration_seconds: Math.round(minutes * 60) } : { kind: timerKind };
    const payload: CreateAttemptRequest = {
      scope, mode, selection_preference: preference, timer,
      random: scope === 'part' ? { part_counts: { [String(part)]: target } }
        : scope === 'custom' ? { part_counts: Object.fromEntries(Object.entries(customCounts).filter(([, count]) => count > 0).map(([p, count]) => [p, count])) }
        : undefined,
    };
    setCreating(true); setError(null);
    try {
      const attempt = await api.createAttempt(payload);
      if (timer.duration_seconds) try { sessionStorage.setItem(`toeic.planned.${attempt.id}`, JSON.stringify({ seconds: timer.duration_seconds })); } catch { /* optional preflight hint */ }
      reloadResumable(); onStarted(attempt.id);
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : '创建练习失败。'); }
    finally { setCreating(false); }
  }

  return <div className="page page-practice">
    <header className="page-head"><div><p className="eyebrow">随机题库</p><h1>开始一轮练习</h1>
      <p className="page-sub">从已核验题库随机抽取完整题组；每轮题目重新编号，记录独立保存。</p></div></header>
    {resumable.length > 0 && <section className="resumable" aria-labelledby="resumable-title">
      <div className="section-head"><h2 id="resumable-title">继续最近的练习</h2><button className="link-btn" onClick={onOpenHistory}>查看历史</button></div>
      <ul className="resumable-list">{resumable.map((item) => <li className="resumable-item" key={item.id}>
        <div className="resumable-main"><strong>{practiceTitle(item.scope, item.created_at)}</strong><p className="resumable-meta">{MODE_LABEL[item.mode]} · {item.question_count} 题 · 已答 {item.answered_count}</p></div>
        <button className="btn btn-primary" onClick={() => onOpenAttempt(item.id)}>{item.status === 'submitted' || item.status === 'expired' ? '查看记录' : '继续作答'}</button>
      </li>)}</ul>
    </section>}
    {catalogError && <section className="composer"><h2>题库暂不可用</h2><p>{catalogError}</p><button className="btn btn-primary" onClick={() => void loadCatalog()}>重试</button></section>}
    {loading && <Loading label="正在读取随机题库…" />}
    {catalog && !loading && <section className="composer" aria-label="随机练习设置">
      <div className="composer-block"><Field label="练习范围"><div className="chip-row" role="radiogroup" aria-label="练习范围">{SCOPES.map((value) => <button key={value} type="button" role="radio" aria-checked={scope === value} className="chip" data-active={scope === value} onClick={() => changeScope(value)}>{SCOPE_LABEL[value]}</button>)}</div></Field></div>
      {scope === 'part' && <div className="composer-block"><Field label="Part 与目标题数" hint="只能抽取完整题组；目标数须能由该 Part 的题组大小组成。"><div className="field-row"><select aria-label="Part" value={part} onChange={(e) => setPart(Number(e.target.value))}>{PARTS.map((n) => <option key={n} value={n}>{PART_LABEL[n]}</option>)}</select><input aria-label="目标题数" type="number" min={1} value={target} onChange={(e) => setTarget(Number(e.target.value) || 0)} /></div></Field></div>}
      {scope === 'custom' && <div className="composer-block"><Field label="自选题组目标数" hint="逐 Part 设置题数；每个目标都必须由该 Part 的完整题组组成，留空或填 0 表示不选。"><div className="pool-part-counts">{PARTS.map((p) => <label key={p}>{PART_LABEL[p]}<input aria-label={`${PART_LABEL[p]}目标题数`} type="number" min={0} value={customCounts[p] ?? 0} onChange={(e) => setCustomCounts((old) => ({ ...old, [p]: Number(e.target.value) || 0 }))} /><span>{catalog.parts.find((item) => item.part === p)?.group_count ?? 0} 组可选</span></label>)}</div></Field></div>}
      <div className="composer-block"><Field label="选题偏好" hint="这是排序偏好，不是硬性筛除；候选不足时会从其余题组补足目标数量。"><div className="chip-row" role="radiogroup" aria-label="选题偏好">{PREFERENCES.map(([key, label]) => <button key={key} type="button" role="radio" aria-checked={preference === key} className="chip chip-compact" data-active={preference === key} onClick={() => setPreference(key)}>{label}</button>)}</div></Field></div>
      <div className="composer-block"><Field label="模式与计时"><div className="chip-row" role="group" aria-label="模式"><button className="chip" data-active={mode === 'practice'} onClick={() => setMode('practice')}>练习</button><button className="chip" data-active={mode === 'exam'} onClick={() => setMode('exam')}>模拟</button></div>
        {mode === 'exam' && ['full', 'listening', 'reading'].includes(scope) ? <p className="field-note">固定时长：{scope === 'full' ? 120 : scope === 'listening' ? 45 : 75} 分钟。完整模拟听力播放结束后仍按听力截止时间等待。</p> : (
          <div className="timer-fields" role="group" aria-label="计时设置">
            <label className="timer-field">
              <span className="timer-field-label">计时方式</span>
              <select aria-label="计时方式" value={timerKind} onChange={(e) => setTimerKind(e.target.value as TimerKind)}>
                {(['countdown', 'countup', 'none'] as TimerKind[]).map((v) => <option value={v} key={v}>{TIMER_LABEL[v]}</option>)}
              </select>
            </label>
            {timerKind === 'countdown' && <label className="timer-field timer-duration-field">
              <span className="timer-field-label">倒计时时长</span>
              <span className="timer-duration-control">
                <input aria-label="计时分钟" aria-describedby="timer-duration-hint" type="number" inputMode="numeric"
                  min={1} max={300} value={minutes} onChange={(e) => changeMinutes(Number(e.target.value) || 0)} />
                <span className="timer-unit" aria-hidden="true">分钟</span>
              </span>
              <span id="timer-duration-hint" className="timer-field-hint">可设置 1–300 分钟</span>
            </label>}
          </div>
        )}
      </Field></div>
      <div className="composer-summary"><p>{scope === 'part' ? `目标 ${target} 题` : scope === 'custom' ? `自选目标 ${Object.values(customCounts).reduce((sum, count) => sum + count, 0)} 题` : `题库 ${catalog.question_count} 题`} · {scope === 'full' && mode === 'exam' ? '听力 45 分钟，阅读 75 分钟' : scope === 'listening' && mode === 'exam' ? '听力 45 分钟' : scope === 'reading' && mode === 'exam' ? '阅读 75 分钟' : '随机抽取完整题组'}</p>
        {!feasible && <p className="summary-warn">当前题库无法按完整题组满足此范围和目标数，请调整目标或稍后重试。</p>}{error && <Banner tone="error" title="无法创建">{error}</Banner>}
        <button className="btn btn-primary btn-lg" disabled={!feasible || creating} onClick={() => void createAttempt()}>{creating ? '正在抽取…' : '随机抽取并开始'}</button>
      </div>
      <p className="license-note">仅供个人学习使用，请勿用于商业用途。</p>
    </section>}
    {catalog && catalog.question_count === 0 && <EmptyBlock title="题库为空" hint="当前没有可用的练习题。" />}
  </div>;
}

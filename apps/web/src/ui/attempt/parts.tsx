import { useMemo, useState } from 'react';
import { MaterialContent, MarkdownText, MarkdownInline } from '../MaterialContent';
import { WorkspaceViewToggle, type WorkspaceView } from '../WorkspaceViewToggle';
import type { Attempt, AttemptQuestion } from '../../domain/types';
import { MODE_LABEL, PART_LABEL, SCOPE_LABEL, formatClock, practiceTitle } from '../../domain/format';
import { Banner, Tag } from '../components';
import type { useAudioController } from './media';
import { stageLock, isCurrentPhaseQuestion } from './stageLock';
import {
  headerContext,
  headerTimerText,
  plannedDurationText,
  readPlannedSeconds,
} from './headerMeta';
import { examDuration } from './examDuration';
import {
  ANSWER_CARD_FILTERS,
  filterCounts,
  visibleEntries,
  type AnswerCardFilter,
  type CardEntry,
} from './answerCardFilter';

export type SaveBadge = { tone: 'good' | 'warn' | 'bad' | 'info' | 'neutral'; label: string };

export function StickyHeader({
  attempt,
  clockDisplay,
  clockExpired,
  saveBadge,
  answered,
  flagged,
  readOnly,
  onExit,
  onSubmit,
  onTogglePause,
  submitting,
  view,
  onView,
}: {
  attempt: Attempt;
  clockDisplay: string;
  clockExpired: boolean;
  saveBadge: SaveBadge;
  answered: number;
  flagged: number;
  readOnly: boolean;
  onExit: () => void;
  onSubmit: () => void;
  onTogglePause: () => void;
  submitting: boolean;
  view: WorkspaceView;
  onView: (view: WorkspaceView) => void;
}) {
  return (
    <header className="sticky-header" data-testid="sticky-header">
      <div className="sticky-left">
        <button type="button" className="link-btn" onClick={onExit}>
          ← 返回
        </button>
        <div className="sticky-title">
          <strong>{practiceTitle(attempt.scope, attempt.created_at)}</strong>
          <span data-testid="header-context">
            {headerContext({
              scope: attempt.scope,
              mode: attempt.mode,
              phase: attempt.timing.phase,
              status: attempt.status,
            })}
          </span>
        </div>
      </div>
      <div className="sticky-right">
        <div className="workspace-view-count">
          <WorkspaceViewToggle view={view} onChange={onView} />
          <span className="sticky-stat" data-testid="answered-count">已答 {answered}/{attempt.question_count}</span>
        </div>
        {flagged > 0 ? <span className="sticky-stat">标记 {flagged}</span> : null}
        <span
          className="timer"
          data-testid="timer"
          data-expired={clockExpired}
          data-kind={attempt.timing.kind}
          data-started={attempt.status !== 'ready'}
        >
          {headerTimerText({ status: attempt.status, kind: attempt.timing.kind, display: clockDisplay })}
        </span>
        <span className="save-badge" data-tone={saveBadge.tone} data-testid="save-state">
          {readOnly ? '只读' : saveBadge.label}
        </span>
        {attempt.mode === 'practice' && attempt.timing.can_pause && !readOnly ? (
          <button type="button" className="btn btn-ghost" onClick={onTogglePause} data-testid="pause-button">
            {attempt.timing.is_paused ? '继续' : '暂停'}
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-primary"
          onClick={onSubmit}
          disabled={submitting || readOnly}
          data-testid="submit-button"
        >
          {submitting ? '交卷中…' : '交卷'}
        </button>
      </div>
    </header>
  );
}

export function Preflight({
  attempt,
  starting,
  error,
  onStart,
  onExit,
  volume,
  muted,
  onVolume,
  onToggleMute,
}: {
  attempt: Attempt;
  starting: boolean;
  error: string | null;
  onStart: () => void;
  onExit: () => void;
  volume: number;
  muted: boolean;
  onVolume: (value: number) => void;
  onToggleMute: () => void;
}) {
  const hasAudio = attempt.audio_queue.length > 0;
  const strict = attempt.mode === 'exam';
  return (
    <div className="preflight" data-testid="preflight">
      <div className="preflight-card">
        <p className="eyebrow">考前确认</p>
        <h1>{practiceTitle(attempt.scope, attempt.created_at)}</h1>
        <ul className="preflight-list">
          <li>
            <span>范围</span>
            <strong>
              {SCOPE_LABEL[attempt.scope]} · {attempt.question_count} 题
              {attempt.parts.length > 0 ? ` · ${attempt.parts.map((part) => `Part ${part}`).join('、')}` : ''}
            </strong>
          </li>
          <li>
            <span>模式</span>
            <strong>{MODE_LABEL[attempt.mode]}</strong>
          </li>
          <li>
            <span>时长</span>
            <strong data-testid="preflight-duration">
              {attempt.status === 'ready'
                ? examDuration({
                    scope: attempt.scope,
                    mode: attempt.mode,
                    audioQueue: attempt.audio_queue,
                    isPoolAttempt: attempt.exam_ids.includes('pool'),
                    timerConfig: attempt.timer_config,
                    timerKind: attempt.timing.kind,
                    plannedSeconds: attempt.timer_config ? null : readPlannedSeconds(attempt.id),
                  }).text
                : plannedDurationText({
                    kind: attempt.timing.kind,
                    remainingMs: attempt.timing.remaining_ms,
                    phase: attempt.timing.phase,
                  })}
              {attempt.timing.phase === 'listening' || attempt.timing.phase === 'reading'
                ? ` · 当前阶段：${attempt.timing.phase === 'listening' ? '听力' : '阅读'}`
                : ''}
            </strong>
          </li>
          <li>
            <span>音频</span>
            <strong>
              {hasAudio
                ? `${attempt.audio_queue.length} 段音轨 · ${strict ? '模拟中不可暂停/拖动/倍速' : '练习中可暂停/重听/倍速'}`
                : '本轮不含音频'}
            </strong>
          </li>
          <li>
            <span>保存</span>
            <strong>答案实时保存到本机服务，刷新可恢复</strong>
          </li>
        </ul>
        {hasAudio ? (
          <div className="preflight-audio">
            <p>
              {strict
                ? '模拟要求先确认浏览器允许播放，再开始计时。'
                : '建议先试音，确认音量后再开始。'}
            </p>
            <div className="audio-volume">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={onToggleMute}
                aria-pressed={muted}
                data-testid="preflight-mute"
              >
                {muted ? '取消静音' : '静音'}
              </button>
              <label className="volume">
                <span className="sr-only">音量</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={volume}
                  onChange={(event) => onVolume(Number(event.target.value))}
                  data-testid="preflight-volume"
                />
              </label>
              <span className="volume-value">{Math.round(volume * 100)}%</span>
            </div>
          </div>
        ) : null}
        {error ? (
          <Banner tone="error" title="无法开始">
            {error}
          </Banner>
        ) : null}
        <div className="preflight-actions">
          <button type="button" className="btn btn-secondary" onClick={onExit}>
            返回
          </button>
          <button
            type="button"
            className="btn btn-primary btn-lg"
            onClick={onStart}
            disabled={starting}
            data-testid="start-button"
          >
            {starting ? '正在开始…' : strict ? '试音并开始模拟' : '开始作答'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ClosedNotice({ attempt, onOpenReport }: { attempt: Attempt; onOpenReport: () => void }) {
  return (
    <div className="preflight">
      <div className="preflight-card">
        <p className="eyebrow">本轮已结束</p>
        <h1>{practiceTitle(attempt.scope, attempt.created_at)}</h1>
        <p>
          该轮已{attempt.status === 'expired' ? '到时结束' : '交卷'}，成绩与复盘为只读记录。重做会创建新的练习记录。
        </p>
        <div className="preflight-actions">
          <button type="button" className="btn btn-primary" onClick={onOpenReport} data-testid="open-report">
            查看报告
          </button>
        </div>
      </div>
    </div>
  );
}

export function AudioBar({
  attempt,
  audio,
  paused,
  question,
  disabled = false,
}: {
  attempt: Attempt;
  audio: ReturnType<typeof useAudioController>;
  paused: boolean;
  question?: AttemptQuestion;
  disabled?: boolean;
}) {
  const strict = attempt.mode === 'exam';
  const { state } = audio;
  const matching = question?.section === 'listening'
    ? attempt.audio_queue.find((item) => item.question_ids.includes(question.id)) : undefined;
  const group = question ? attempt.groups.find((item) => item.id === question.group_id) : undefined;
  const target = matching && group && matching.question_ids.length === group.question_ids.length &&
    matching.question_ids.every((id) => group.question_ids.includes(id)) ? matching : undefined;
  const shared = (target?.question_ids.length ?? 0) > 1;
  return (
    <section className="audio-bar" aria-label="音频控制" data-testid="audio-bar">
      <div className="audio-head">
        <div>
          <strong>
            音轨 {state.queueIndex + 1} / {attempt.audio_queue.length}
          </strong>
          <span>
            {formatClock(state.positionSeconds)} / {formatClock(state.durationSeconds)}
          </span>
        </div>
        <div className="audio-state">
          {state.waiting ? <Tag tone="warn">缓冲中</Tag> : null}
          {state.stalled ? <Tag tone="bad">播放中断</Tag> : null}
          {strict ? <Tag tone="info">模拟：按考试时间播放</Tag> : <Tag tone="neutral">练习：可自由控制</Tag>}
        </div>
      </div>
      {state.error ? <p className="audio-error">{state.error}</p> : null}
      {state.needsResume ? (
        <div className="audio-resume" role="status">
          <span>音频没有在播放。刷新或切换标签后会回到上次的位置继续。</span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void audio.resumeAfterInterruption()}
            data-testid="audio-reauthorize"
          >
            重新授权播放
          </button>
        </div>
      ) : null}
      {strict ? (
        <p className="audio-note">模拟中不可暂停、拖动或倍速。卡顿或掉线会被标记为中断并保留进度。</p>
      ) : (
        <div className="audio-controls">
          {target ? (
            <button type="button" className="btn btn-secondary" disabled={paused || disabled}
              onClick={() => question && void audio.replayQuestion(question.id)} data-testid="audio-replay">
              {shared ? '重放本篇' : '重放本题'}
            </button>
          ) : null}
          <button type="button" className="btn btn-secondary" disabled={paused || disabled}
            onClick={() => audio.seek(state.positionSeconds - 10)} data-testid="audio-backward">快退 10 秒</button>
          <button
            type="button"
            className="btn btn-secondary"
            // While the practice timer is paused the media is paused with it;
            // the top-level "继续" control resumes both together.
            disabled={paused || disabled}
            onClick={() => (state.playing ? audio.pause() : void audio.play())}
            title={paused ? '已暂停，请先用顶部的“继续”恢复' : undefined}
            data-testid="audio-play"
          >
            {paused ? '已暂停' : state.playing ? '暂停' : '播放'}
          </button>
          <button type="button" className="btn btn-secondary" disabled={paused || disabled}
            onClick={() => audio.seek(state.positionSeconds + 10)} data-testid="audio-forward">快进 10 秒</button>
          <label className="seek">
            <span className="sr-only">跳转</span>
            <input
              type="range"
              disabled={paused || disabled}
              min={0}
              max={Math.max(1, state.durationSeconds)}
              step={1}
              value={Math.floor(state.positionSeconds)}
              onChange={(event) => audio.seek(Number(event.target.value))}
              data-testid="audio-seek"
            />
          </label>
          <label className="rate">
            <span>倍速</span>
            <select
              disabled={paused || disabled}
              value={state.playbackRate}
              onChange={(event) => audio.setRate(Number(event.target.value))}
              data-testid="audio-rate"
            >
              <option value={0.75}>0.75×</option>
              <option value={1}>1×</option>
              <option value={1.25}>1.25×</option>
              <option value={1.5}>1.5×</option>
              <option value={2}>2×</option>
            </select>
          </label>
        </div>
      )}
      {!strict && target ? (
        <p className="audio-note">
          {shared ? '同篇材料中的题目共用一段录音；重放从本篇开头开始，到本篇结尾停止。' : '重放从本题开头开始，到本题结尾停止。'}
          暂停音频不会暂停答题计时。
        </p>
      ) : null}
      <div className="audio-volume">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={audio.toggleMuted}
          aria-pressed={state.muted}
          data-testid="audio-mute"
        >
          {state.muted ? '取消静音' : '静音'}
        </button>
        <label className="volume">
          <span className="sr-only">音量</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={state.volume}
            onChange={(event) => audio.setVolume(Number(event.target.value))}
            data-testid="audio-volume"
          />
        </label>
        <span className="volume-value">{Math.round(state.volume * 100)}%</span>
      </div>
    </section>
  );
}

export function QuestionPanel({
  question,
  group,
  answer,
  readOnly,
  attempt,
  onSelect,
  onFlag,
  solution,
}: {
  question: AttemptQuestion;
  group: Attempt['groups'][number];
  answer: { option_id: string | null; flagged: boolean; visited: boolean; dirty: boolean } | undefined;
  readOnly: boolean;
  attempt: Attempt;
  onSelect: (optionId: 'A' | 'B' | 'C' | 'D') => void;
  onFlag: () => void;
  solution?: { answer: string; selected: string | null };
}) {
  // (P0 fix) Listening questions are editable WHILE listening runs; they lock
  // only when the exam enters reading. This used to disable every option.
  const lock = stageLock({
    questionPart: question.part,
    questionId: question.id,
    section: question.section,
    phase: attempt.timing.phase,
    phaseQuestionIds: attempt.timing.phase_question_ids,
    status: attempt.status,
    isPaused: attempt.timing.is_paused,
    mode: attempt.mode,
  });
  const locked = !lock.editable || !isCurrentPhaseQuestion({ phaseQuestionIds: attempt.timing.phase_question_ids, questionId: question.id });
  const review = ['submitted', 'expired'].includes(attempt.status) ? solution : undefined;
  const sharedMaterials = group.materials;
  const displayNumber = attempt.questions.findIndex((item) => item.id === question.id) + 1;

  return (
    <section className="question-panel" data-testid="practice-form" data-question-id={question.id}>
      <div className="question-head">
        <div className="question-meta">
          <Tag tone="neutral">{PART_LABEL[question.part] ?? `Part ${question.part}`}</Tag>
          <span className="question-number">
            第 {displayNumber} 题 · {question.section === 'listening' ? '听力' : '阅读'}
          </span>
        </div>
        {!review && <button
          type="button"
          className="btn btn-ghost question-flag"
          onClick={onFlag}
          disabled={readOnly || locked}
          aria-pressed={answer?.flagged ?? false}
          data-testid="flag-button"
        >
          <span aria-hidden="true">⚑</span> 标记本题
        </button>}
      </div>

      <MaterialContent materials={sharedMaterials} />

      {question.stem ? <MarkdownText className="question-stem" text={question.stem} flow="prose" /> : null}

      <div className="options" role="radiogroup" aria-label={`第 ${displayNumber} 题选项`}>
        {question.options.map((option) => {
          const selected = answer?.option_id === option.id;
          const labelOnly = isLabelOnly(option.text, option.id);
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              className="option"
              data-selected={selected}
              data-correct={review ? option.id === review.answer : undefined}
              data-wrong={review ? selected && option.id !== review.answer : undefined}
              disabled={readOnly || locked}
              data-locked={locked}
              title={lock.reason ?? undefined}
              onClick={(event) => {
                // Text selection inside an option (drag-copy) must not toggle it.
                if (isTextSelection(event)) return;
                onSelect(option.id);
              }}
              data-testid={`option-${question.id}-${option.id}`}
            >
              <span className="option-key">{option.id}</span>
              <MarkdownInline className="option-text" text={labelOnly ? `选项 ${option.id}` : option.text} />
              {review && option.id === review.answer ? <Tag tone="good">正确答案</Tag> : null}
              {selected ? <span className="option-mark">{review ? '你的选择' : '已选'}</span> : null}
            </button>
          );
        })}
      </div>
      {lock.reason ? (
        <p className="phase-note" data-testid="stage-lock-note">
          {lock.reason}
        </p>
      ) : null}
    </section>
  );
}

function isLabelOnly(text: string, id: string): boolean {
  const trimmed = text.trim();
  return trimmed === '' || trimmed === id || trimmed === `${id}.` || trimmed === `(${id})`;
}

function isTextSelection(event: React.MouseEvent): boolean {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return false;
  const node = selection.anchorNode;
  return node !== null && event.currentTarget.contains(node);
}

export function AnswerCard({
  attempt,
  answers,
  currentIndex,
  onJump,
  results,
}: {
  attempt: Attempt;
  answers: Record<string, { option_id: string | null; flagged: boolean; visited: boolean; dirty: boolean }>;
  currentIndex: number;
  onJump: (index: number) => void;
  results?: Record<string, string>;
}) {
  // Display-only filter. It never changes the scope or the jump target.
  const [filter, setFilter] = useState<AnswerCardFilter>('all');

  const entries = useMemo<Array<CardEntry<AttemptQuestion>>>(
    () =>
      attempt.questions.map((question, index) => {
        const answer = answers[question.id];
        return {
          question,
          index,
          state: {
            optionId: answer?.option_id ?? null,
            flagged: Boolean(answer?.flagged),
            visited: Boolean(answer?.visited),
          },
          isCurrent: index === currentIndex,
        };
      }),
    [answers, attempt.questions, currentIndex],
  );
  const counts = useMemo(() => filterCounts(entries), [entries]);
  const visible = useMemo(() => visibleEntries(entries, filter), [entries, filter]);

  return (
    <aside className="answer-card" aria-label="答题卡" data-testid="answer-card">
      <div className="answer-card-head">
        <h2>答题卡</h2>
        <div className="legend">
          <span>
            <i className="legend-swatch" data-kind="answered" /> 已答
          </span>
          <span>
            <i className="legend-swatch" data-kind="visited" /> 已访问
          </span>
          <span>
            <i className="legend-swatch" data-kind="flagged" /> 标记
          </span>
          <span>
            <i className="legend-swatch" data-kind="current" /> 当前
          </span>
        </div>
      </div>
      <div className="answer-filters" role="group" aria-label="答题卡筛选" data-testid="answer-card-filters">
        {ANSWER_CARD_FILTERS.map((item) => (
          <button
            key={item.key}
            type="button"
            className="chip chip-compact"
            data-active={filter === item.key}
            aria-pressed={filter === item.key}
            onClick={() => setFilter(item.key)}
            data-testid={`answer-filter-${item.key}`}
          >
            {item.label}
            <span className="chip-count">{counts[item.key]}</span>
          </button>
        ))}
      </div>
      {visible.length === 0 ? (
        <p className="answer-empty" data-testid="answer-filter-empty">
          没有符合条件的题目。
        </p>
      ) : null}
      <div className="answer-grid">
        {visible.map(({ question, index, state: cellState, isCurrent }) => {
          const answered = cellState.optionId !== null;
          const visited = cellState.visited;
          const flagged = cellState.flagged;
          const state = !answered && !visited ? 'untouched' : answered ? 'answered' : 'visited';
          const lock = stageLock({
            questionPart: question.part,
            questionId: question.id,
            section: question.section,
            phase: attempt.timing.phase,
            phaseQuestionIds: attempt.timing.phase_question_ids,
            status: attempt.status,
            isPaused: attempt.timing.is_paused,
            mode: attempt.mode,
          });
          return (
            <button
              key={question.id}
              type="button"
              className="answer-cell"
              data-state={state}
              data-current={isCurrent}
              data-flagged={flagged}
              data-locked={results ? undefined : !lock.editable}
              data-result={results?.[question.id]}
              aria-current={isCurrent ? 'step' : undefined}
              aria-label={`第 ${index + 1} 题，${
                answered ? '已答' : visited ? '已访问未答' : '未访问'
              }${flagged ? '，已标记' : ''}${results?.[question.id] === 'wrong' ? '，错误' : results?.[question.id] === 'correct' ? '，正确' : ''}${!results && !lock.editable ? `，${lock.reason ?? '不可作答'}` : ''}`}
              title={`第 ${index + 1} 题`}
              onClick={() => onJump(index)}
              data-testid={`answer-cell-${question.id}`}
            >
              <span className="cell-index">{index + 1}</span>
              {flagged ? (
                <span className="cell-flag" aria-hidden="true">
                  ●
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </aside>
  );
}

export function saveBadgeFor(state: string, readOnly: boolean): SaveBadge {
  if (readOnly) return { tone: 'neutral', label: '只读' };
  switch (state) {
    case 'saving':
      return { tone: 'info', label: '保存中' };
    case 'saved':
      return { tone: 'good', label: '已保存' };
    case 'failed':
      return { tone: 'bad', label: '保存失败' };
    case 'conflict':
      return { tone: 'warn', label: '待确认' };
    case 'expired':
      return { tone: 'warn', label: '已结束' };
    default:
      return { tone: 'neutral', label: '就绪' };
  }
}

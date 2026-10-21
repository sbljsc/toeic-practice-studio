import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import { getTabId } from '../../domain/tab';
import { useProjectedClock } from '../../domain/clock';
import type { Attempt } from '../../domain/types';
import { Banner, Loading } from '../components';
import { useAnswerPipeline } from './saveQueue';
import { useAudioController } from './media';
import { queueInterruption } from './interruptionDelivery';
import { AnswerCard, AudioBar, ClosedNotice, Preflight, QuestionPanel, StickyHeader, saveBadgeFor } from './parts';
import { TranscriptPanel } from '../TranscriptPanel';
import { ActivityStatistics } from '../ActivityStatistics';
import { useActivity } from './useActivity';
import { nextEligibleIndex, questionEligible } from './workspaceNavigation';
import { keepsSameAudioSegment } from './audioSegment';
import type { WorkspaceView } from '../WorkspaceViewToggle';
import { practiceSubtitleContext } from '../subtitleSync';

interface Props { attemptId: string; onSubmitted: (id: string) => void; onExit: () => void }
const closed = (value: Attempt | null) => !!value && ['submitted', 'expired'].includes(value.status);

export function AttemptWorkspace({ attemptId, onSubmitted, onExit }: Props) {
  const tabId = useMemo(getTabId, []);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const currentAttempt = useRef<Attempt | null>(null);
  const ownershipLost = useRef(false);
  const ownershipEpoch = useRef(0);
  const ended = useRef(false);
  const mounted = useRef(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [clockNotice, setClockNotice] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(true);
  const [takeoverPrompt, setTakeoverPrompt] = useState(false);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [canSubmitSavedOnly, setCanSubmitSavedOnly] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [view, setView] = useState<WorkspaceView>('answer');
  const [autoNext, setAutoNext] = useState(true);
  const [showUnscored] = useState(true);
  const [mediaNotice, setMediaNotice] = useState<string | null>(null);
  const loseOwnership = useCallback(() => {
    if (!ownershipLost.current) ownershipEpoch.current++;
    ownershipLost.current = true; setReadOnly(true);
  }, []);

  const applyAttempt = useCallback((incoming: Attempt) => {
    if (incoming.id !== attemptId) return;
    const previous = currentAttempt.current;
    if (previous?.id === incoming.id && closed(previous) && !closed(incoming)) return;
    let next = incoming;
    if (previous?.id === incoming.id) {
      const answers = { ...incoming.answers };
      for (const [id, value] of Object.entries(previous.answers)) {
        if (value.revision > (answers[id]?.revision ?? -1)) answers[id] = value;
      }
      // A slow answer response must not move the phase/clock backwards.
      if (incoming.timing.elapsed_ms < previous.timing.elapsed_ms && previous.status === 'running') {
        next = { ...incoming, answers, timing: previous.timing,
          status: previous.status, audio_elapsed_ms: previous.audio_elapsed_ms };
      } else next = { ...incoming, answers };
      if (previous.owner_tab_id === tabId && incoming.owner_tab_id !== tabId) {
        if (!ownershipLost.current) ownershipEpoch.current++;
        ownershipLost.current = true;
      }
      if (previous.timing.phase === 'listening' && next.timing.phase === 'reading') {
        const first = next.questions.findIndex((q) => q.section === 'reading');
        if (first >= 0) setCurrentIndex(first);
      }
    }
    currentAttempt.current = next;
    if (closed(next)) ended.current = true;
    setAttempt(next);
    setReadOnly(ownershipLost.current || next.owner_tab_id !== tabId);
  }, [attemptId, tabId]);

  useEffect(() => {
    let live = true;
    currentAttempt.current = null; ownershipLost.current = false; ended.current = false;
    setAttempt(null); setLoadError(null); setReadOnly(true);
    setSubmitError(null); setMediaNotice(null); setClockNotice(null); setView('answer');
    void api.getAttempt(attemptId).then(async (loaded) => {
      if (!live) return;
      applyAttempt(loaded); setCurrentIndex(loaded.current_index);
      if (closed(loaded)) return;
      try {
        const claimed = await api.claim(attemptId, false);
        if (live) { ownershipEpoch.current++; applyAttempt(claimed); }
      } catch (error) {
        if (!live) return;
        setReadOnly(true);
        if (!(error instanceof ApiError && error.status === 409))
          setBanner(error instanceof Error ? error.message : '无法取得作答权，请重试。');
      }
    }).catch((error) => live && setLoadError(error instanceof Error ? error.message : '读取失败。'));
    return () => { live = false; };
  }, [applyAttempt, attemptId]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; currentAttempt.current = null; };
  }, []);

  const recordInterruption = useCallback((reason: string, id?: string) => {
    const target = id ?? currentAttempt.current?.id;
    if (!target || ended.current || (currentAttempt.current?.id === target && ownershipLost.current)) return;
    queueInterruption({ event_id: crypto.randomUUID(), attempt_id: target,
      owner_tab_id: tabId, reason, occurred_at_ms: Date.now() });
    if (mounted.current) setMediaNotice(reason);
  }, [tabId]);

  const isClosed = closed(attempt);
  const pipeline = useAnswerPipeline({ attempt: attempt ?? EMPTY_ATTEMPT, readOnly,
    onAttempt: applyAttempt, onBanner: setBanner, onOwnershipLost: loseOwnership,
    ownershipEpoch: () => ownershipEpoch.current });
  const activity = useActivity(attempt, currentIndex, view === 'answer', !readOnly && !isClosed);
  const clock = useProjectedClock(attempt?.timing ?? null, attempt?.status);
  useEffect(() => {
    if (canSubmitSavedOnly && pipeline.saveState === 'saved') {
      setCanSubmitSavedOnly(false); setSubmitError(null);
    }
  }, [canSubmitSavedOnly, pipeline.saveState]);
  const audio = useAudioController({
    attempt: attempt ?? EMPTY_ATTEMPT, active: !readOnly && !isClosed,
    onPracticeMediaState: async (state, target) => {
      const current = currentAttempt.current;
      const id = target ?? current?.id;
      if (id && !(current?.id === id && ownershipLost.current)) await api.mediaState(id, state);
    },
    onStall: recordInterruption,
  });

  const syncClock = useCallback(async () => {
    const current = currentAttempt.current;
    if (!current || current.id !== attemptId) return;
    const epoch = ownershipEpoch.current;
    try {
      const response = await api.clock(current.id);
      const latest = currentAttempt.current;
      if (!latest || latest.id !== current.id) return;
      if (epoch !== ownershipEpoch.current) return;
      applyAttempt({ ...latest, timing: response.timing, audio_elapsed_ms: response.audio_elapsed_ms,
        status: response.status, owner_tab_id: response.owner_tab_id === undefined
          ? latest.owner_tab_id : response.owner_tab_id });
      setClockNotice(null);
      if (['submitted', 'expired'].includes(response.status)) onSubmitted(current.id);
    } catch {
      if (epoch === ownershipEpoch.current && currentAttempt.current?.id === current.id)
        setClockNotice('暂时无法同步时间，恢复连接后仍按原截止时间结算。');
    }
  }, [applyAttempt, attemptId, onSubmitted]);
  useEffect(() => {
    const updated = (event: Event) => {
      if ((event as CustomEvent<{ attemptId: string }>).detail.attemptId === attemptId) void syncClock();
    };
    window.addEventListener('toeic:interruption-updated', updated);
    return () => window.removeEventListener('toeic:interruption-updated', updated);
  }, [attemptId, syncClock]);
  useEffect(() => {
    if (!attempt || isClosed) return;
    const timer = setInterval(() => void syncClock(), 5000);
    const refresh = () => void syncClock();
    window.addEventListener('focus', refresh); window.addEventListener('online', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      clearInterval(timer); window.removeEventListener('focus', refresh);
      window.removeEventListener('online', refresh); document.removeEventListener('visibilitychange', refresh);
    };
  }, [attempt?.id, isClosed, syncClock]);
  useEffect(() => {
    if (!clock.expired || attempt?.status !== 'running') return;
    void syncClock();
    const boundary = setTimeout(() => void syncClock(), 80);
    return () => clearTimeout(boundary);
  }, [clock.expired, attempt?.status, attempt?.timing.phase, syncClock]);

  const jumpTo = useCallback((index: number) => {
    const current = currentAttempt.current;
    if (!current) return;
    const bounded = Math.max(0, Math.min(current.questions.length - 1, index));
    const previous = current.questions[currentIndex];
    setCurrentIndex(bounded);
    const target = current.questions[bounded];
    if (target) {
      pipeline.markVisited(target.id);
      // Moving to a question in another clip must stop the previous clip.
      // Questions sharing one clip keep playing where they are.
      if (!keepsSameAudioSegment(current.audio_queue, previous?.id, target.id)) {
        audio.selectQuestion(target.id);
      }
    }
    if (!readOnly && !submitting)
      void api.setPosition(current.id, bounded).catch(() => undefined);
  }, [audio, currentIndex, pipeline, readOnly, submitting]);

  const startAttempt = useCallback(async () => {
    const current = currentAttempt.current;
    if (!current || starting) return;
    if (readOnly) { setSubmitError('当前页面只读，请先接管作答。'); return; }
    setStarting(true); setSubmitError(null);
    try {
      const ready = current.audio_queue.length === 0 || await audio.unlock();
      if (!ready) { setSubmitError('音频播放准备未完成，尚未开始计时。'); return; }
      if (ownershipLost.current) return;
      applyAttempt(await api.start(current.id, current.audio_queue.length > 0));
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '开始失败。');
    } finally { setStarting(false); }
  }, [applyAttempt, audio, readOnly, starting]);

  const togglePause = useCallback(async () => {
    const current = currentAttempt.current;
    if (!current || current.mode !== 'practice' || readOnly) return;
    try {
      if (!current.timing.is_paused) {
        const flushed = await pipeline.flushPending();
        if (!flushed.ok) { setBanner('尚有未确认答案，暂停未成功。请先重试保存。'); return; }
      }
      applyAttempt(current.timing.is_paused ? await api.resume(current.id) : await api.pause(current.id));
    } catch (error) { setBanner(error instanceof Error ? error.message : '暂停或继续失败。'); }
  }, [applyAttempt, pipeline, readOnly]);

  const submitAttempt = useCallback(async (savedOnly = false) => {
    const current = currentAttempt.current;
    if (!current || submitting || readOnly || ownershipLost.current) return;
    if (current.status === 'ready') { setSubmitError('请先开始作答，或返回选择范围。'); return; }
    setSubmitting(true); setSubmitError(null);
    try {
      if (!savedOnly) {
        const flushed = await pipeline.flushPending();
        if (!flushed.ok) {
          setCanSubmitSavedOnly(true);
          setSubmitError('尚有答案未确认保存，当前没有交卷。请重试保存，或仅交已保存的答案；其余草稿保留但不计分。');
          return;
        }
      }
      await api.submit(current.id); ended.current = true; onSubmitted(current.id);
    } catch (error) { setSubmitError(error instanceof Error ? error.message : '交卷失败，请重试。'); }
    finally { setSubmitting(false); }
  }, [onSubmitted, pipeline, readOnly, submitting]);

  const takeOver = useCallback(async () => {
    const current = currentAttempt.current;
    if (!current) return;
    try {
      const claimed = await api.claim(current.id, true);
      ownershipEpoch.current++; ownershipLost.current = false;
      applyAttempt(claimed); setTakeoverPrompt(false);
    } catch (error) { setBanner(error instanceof Error ? error.message : '接管失败。'); }
  }, [applyAttempt]);
  const continuePractice = useCallback(async () => {
    const current = currentAttempt.current;
    if (!current || readOnly) return;
    try {
      applyAttempt(await api.continuePractice(current.id)); setMediaNotice(null);
    } catch (error) { setBanner(error instanceof Error ? error.message : '无法续做。'); }
  }, [applyAttempt, readOnly]);

  if (loadError) {
    return (
      <div className="page">
        <Banner tone="error" title="无法打开该轮练习">
          {loadError}
        </Banner>
        <button type="button" className="btn btn-secondary" onClick={onExit}>
          返回练习首页
        </button>
      </div>
    );
  }

  if (!attempt) {
    return (
      <div className="page">
        <Loading label="正在恢复作答记录…" />
      </div>
    );
  }

  const saveBadge = saveBadgeFor(pipeline.saveState, readOnly);
  const question = attempt.questions[currentIndex];
  const clipsFinished = attempt.audio_queue.length > 0 && audio.state.queueIndex === attempt.audio_queue.length - 1 &&
    audio.state.durationSeconds > 0 && audio.state.positionSeconds >= audio.state.durationSeconds - 0.25;
  const subtitle = practiceSubtitleContext(attempt, audio.state.queueIndex);
  const group = question ? attempt.groups.find((item) => item.id === question.group_id) : undefined;
  const answered = Object.values(pipeline.answers).filter((item) => item.option_id !== null).length;
  const flagged = Object.values(pipeline.answers).filter((item) => item.flagged).length;

  return (
    <div className="workspace" data-testid="attempt-workspace">
      {attempt.audio_queue.length > 0 ? (
        <audio ref={audio.elementRef} preload="auto" data-testid="audio-element" />
      ) : null}
      <StickyHeader
        attempt={attempt}
        clockDisplay={attempt.status === 'ready' ? '未开始' : clock.display}
        clockExpired={clock.expired}
        saveBadge={saveBadge}
        answered={answered}
        flagged={flagged}
        readOnly={readOnly}
        onExit={onExit}
        onSubmit={() => void submitAttempt()}
        onTogglePause={() => void togglePause()}
        submitting={submitting}
        view={view}
        onView={setView}
      />

      {banner ? (
        <div className="workspace-banner">
          <Banner
            tone="error"
            title="保存未确认"
            action={
              <button type="button" className="btn btn-secondary" onClick={() => void pipeline.retryAll()}>
                立即重试
              </button>
            }
          >
            {banner}
          </Banner>
        </div>
      ) : null}

      {clockNotice ? <div className="workspace-banner"><Banner tone="warn" title="时间同步暂不可用">{clockNotice}</Banner></div> : null}
      {attempt.mode === 'exam' && (attempt.scope === 'full' || attempt.scope === 'listening') &&
        attempt.timing.phase === 'listening' && clipsFinished ? (
          <div className="workspace-banner"><Banner tone="info" title="听力音轨已播放完毕">
            音轨总时长为 {Math.floor(audio.state.queueTotalSeconds / 60)} 分 {Math.round(audio.state.queueTotalSeconds % 60)} 秒。听力阶段仍按服务器截止时间计时，剩余 {clock.display}；请等待阶段结束后继续。
          </Banner></div>
        ) : null}
      {mediaNotice || attempt.timing.integrity === 'interrupted' ? (
        <div className="workspace-banner">
          <Banner
            tone="warn"
            title={mediaNotice ?? '本轮存在中断记录'}
            action={
              attempt.timing.integrity === 'interrupted' ? (
                <button type="button" className="btn btn-secondary" onClick={() => void continuePractice()}>
                  以练习方式续做
                </button>
              ) : null
            }
          >
            {attempt.timing.integrity === 'interrupted'
              ? '本次已记录中断，进度保留，不计入有效模拟。'
              : '正在记录中断；进度保留，计时继续。'}
          </Banner>
        </div>
      ) : null}

      {takeoverPrompt ? (
        <div className="workspace-banner">
          <Banner
            tone="info"
            title="另一个标签页正在作答"
            action={
              <div className="banner-buttons">
                <button type="button" className="btn btn-primary" onClick={() => void takeOver()}>
                  接管作答
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => setTakeoverPrompt(false)}>
                  保持只读
                </button>
              </div>
            }
          >
            当前标签为只读。接管后旧窗口不会覆盖新写入。
          </Banner>
        </div>
      ) : null}

      {readOnly && !takeoverPrompt ? (
        <div className="workspace-banner">
          <Banner
            tone="info"
            title="只读模式"
            action={
              <button type="button" className="btn btn-secondary" onClick={() => setTakeoverPrompt(true)}>
                请求接管
              </button>
            }
          >
            另一个标签页持有本轮作答权。
          </Banner>
        </div>
      ) : null}

      {pipeline.conflict ? (
        <div className="workspace-banner">
          <Banner tone="warn" title="答案版本冲突">
            <p>另一处已经改过这道题（例如另一个标签页）。请选择保留哪一份，不会自动覆盖。</p>
            <p>
              第 {attempt.questions.find((item) => item.id === pipeline.conflict?.questionId)?.number ?? '—'} 题：
              已保存 {pipeline.conflict.server.option_id ?? '未选'}；本机草稿 {pipeline.conflict.draft.option_id ?? '未选'}。
            </p>
            <div className="banner-buttons">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => pipeline.resolveConflict('server')}
              >
                保留已保存的
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => pipeline.resolveConflict('local')}
              >
                使用本机草稿
              </button>
            </div>
          </Banner>
        </div>
      ) : null}

      {pipeline.unscoredDrafts.length > 0 && showUnscored ? (
        <div className="workspace-banner">
          <Banner
            tone="warn"
            title={`${pipeline.unscoredDrafts.length} 条本机草稿未计分`}
            action={
              <button type="button" className="btn btn-secondary" onClick={() => pipeline.dismissUnscored()}>
                知道了
              </button>
            }
          >
            这些答案在本机保留但未回灌成绩，也不会进入新的练习记录。
          </Banner>
        </div>
      ) : null}

      {attempt.status === 'ready' ? (
        <Preflight
          attempt={attempt}
          starting={starting}
          error={submitError}
          onStart={() => void startAttempt()}
          onExit={onExit}
          volume={audio.state.volume}
          muted={audio.state.muted}
          onVolume={audio.setVolume}
          onToggleMute={audio.toggleMuted}
        />
      ) : isClosed ? (
        <ClosedNotice attempt={attempt} onOpenReport={() => onSubmitted(attempt.id)} />
      ) : (
        <div className="workspace-body" data-view={view}>
          <main className="workspace-main">
            {attempt.audio_queue.length > 0 && (attempt.mode === 'practice' || attempt.timing.phase === 'listening' ||
              (attempt.timing.phase === 'practice' && (attempt.scope === 'part' || attempt.scope === 'custom'))) ? (
              <AudioBar
                attempt={attempt}
                audio={audio}
                paused={attempt.timing.is_paused}
                question={question}
                disabled={readOnly || submitting || clock.expired}
              />
            ) : null}

            {activity.notice && view === 'statistics' ? <p className="phase-note" role="status">{activity.notice}</p> : null}
            {view === 'statistics' ? <ActivityStatistics activity={activity.activity} live /> : null}
            <div className="answer-workspace-content" hidden={view !== 'answer'}>
            <label className="auto-next-control"><input type="checkbox" checked={autoNext} onChange={(event) => setAutoNext(event.target.checked)} />选择答案后自动下一题</label>
            {subtitle ? (
              <TranscriptPanel key={`${attempt.id}:${subtitle.group.id}`} script={subtitle.script} clip={subtitle.clip}
                sourceTime={subtitle.clip.start_seconds + audio.state.positionSeconds}
                disabled={readOnly || submitting || clock.expired || attempt.timing.is_paused}
                onSentence={(sourceTime) => void audio.playSentence(sourceTime)} />
            ) : null}

            {question && group ? (
              <QuestionPanel
                question={question}
                group={group}
                answer={pipeline.answers[question.id]}
                readOnly={readOnly || submitting || clock.expired}
                attempt={attempt}
                onSelect={(optionId) => {
                  const latest = currentAttempt.current;
                  if (!latest || ownershipLost.current || readOnly || submitting || clock.expired || !questionEligible(latest, question)) return;
                  if (!pipeline.selectOption(question.id, optionId)) return;
                  const next = autoNext ? nextEligibleIndex(latest, currentIndex) : null;
                  if (next !== null) jumpTo(next);
                }}
                onFlag={() => pipeline.toggleFlag(question.id)}
              />
            ) : (
              <div className="state-block">
                <strong>本轮没有题目</strong>
                <span>请返回首页重新选择范围。</span>
              </div>
            )}

            <div className="nav-row">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={currentIndex <= 0}
                onClick={() => jumpTo(currentIndex - 1)}
                data-testid="prev-question"
              >
                上一题
              </button>
              <span className="nav-position">
                本轮第 {currentIndex + 1} / {attempt.questions.length} 题
              </span>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={currentIndex >= attempt.questions.length - 1}
                onClick={() => jumpTo(currentIndex + 1)}
                data-testid="next-question"
              >
                下一题
              </button>
            </div>

            </div>
            {submitError ? (
              <Banner tone="error" title="尚未交卷" action={canSubmitSavedOnly && !readOnly ? (
                <button type="button" className="btn btn-secondary" disabled={submitting}
                  onClick={() => void submitAttempt(true)}>仅交已保存的答案</button>
              ) : undefined}>
                {submitError}
              </Banner>
            ) : null}
          </main>

          {view === 'answer' ? <AnswerCard attempt={attempt} answers={pipeline.answers} currentIndex={currentIndex} onJump={jumpTo} /> : null}
        </div>
      )}
    </div>
  );
}

const EMPTY_ATTEMPT: Attempt = {
  id: '',
  title: '',
  scope: 'reading',
  mode: 'practice',
  status: 'ready',
  created_at: '',
  exam_ids: [],
  parts: [],
  question_count: 0,
  current_index: 0,
  questions: [],
  groups: [],
  answers: {},
  timing: {
    kind: 'none',
    phase: 'finished',
    remaining_ms: null,
    elapsed_ms: 0,
    server_time_ms: 0,
    deadline_at_ms: null,
    can_pause: false,
    is_paused: false,
    integrity: 'valid',
    phase_question_ids: [],
  },
  audio_queue: [],
  audio_elapsed_ms: 0,
  owner_tab_id: null,
  interruptions: [],
};

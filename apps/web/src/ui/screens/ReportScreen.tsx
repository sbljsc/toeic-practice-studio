import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import {
  CAUSES,
  CAUSE_LABEL,
  MODE_LABEL,
  PART_LABEL,
  SCOPE_LABEL,
  percent,
  practiceTitle,
} from '../../domain/format';
import type {
  Attempt,
  AttemptReport,
  Candidate,
  ReportQuestion,
  ReviewCause,
  ReviewWord,
} from '../../domain/types';
import { Banner, ErrorBlock, Loading, Stat, Tag } from '../components';
import { erratumNote } from '../attempt/erratum';
import { ReviewAudioBar } from './ReviewAudioBar';
import { ListeningReview } from './ListeningReview';
import { UnscoredDrafts } from './UnscoredDrafts';
import { pendingInterruptionCount } from '../attempt/interruptionDelivery';
import { reviewEligibility } from './reviewEligibility';
import { ReportRequestGate } from './reportState';
import { ActivityStatistics } from '../ActivityStatistics';
import { WorkspaceViewToggle, type WorkspaceView } from '../WorkspaceViewToggle';
import { AnswerCard, QuestionPanel } from '../attempt/parts';
import { reviewFocusIndex, reviewWorkspace } from './reviewWorkspace';

interface Props {
  attemptId: string;
  focusQuestionId?: string;
  onBack: () => void;
  onRetake: () => void;
  onOpenAttempt: (id: string) => void;
}

export function ReportScreen({ attemptId, focusQuestionId, onBack, onRetake, onOpenAttempt }: Props) {
  const [report, setReport] = useState<AttemptReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<WorkspaceView>(focusQuestionId ? 'answer' : 'statistics');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [retaking, setRetaking] = useState(false);
  const [retakeError, setRetakeError] = useState<string | null>(null);
  // Review replay: the report DTO has no audio queue, so read it from the
  // closed attempt, which still exposes audio_queue after grading.
  const [snapshot, setSnapshot] = useState<Attempt | null>(null);
  const [pendingInterruptions, setPendingInterruptions] = useState(0);
  const requestGate = useRef(new ReportRequestGate()).current;
  requestGate.select(attemptId);

  const refreshPending = useCallback(() => {
    try {
      setPendingInterruptions(pendingInterruptionCount(attemptId));
    } catch {
      setPendingInterruptions(0);
    }
  }, [attemptId]);

  useEffect(() => {
    refreshPending();
  }, [refreshPending]);

  useEffect(() => {
    let active = true;
    setSnapshot(null);
    api
      .getAttempt(attemptId)
      .then((attempt) => {
        if (active) setSnapshot(attempt);
      })
      .catch(() => {
        // Replay is optional; a failure must not break the report.
      });
    return () => {
      active = false;
    };
  }, [attemptId]);

  const load = useCallback(() => {
    const token = requestGate.begin(attemptId);
    if (!token) return;
    setError(null);
    api
      .report(attemptId)
      .then((incoming) => {
        const accepted = requestGate.accept(token, incoming);
        if (accepted) setReport(accepted);
      })
      .catch((cause: unknown) => {
        if (requestGate.current(token)) setError(cause instanceof ApiError ? cause.message : '读取报告失败。');
      });
  }, [attemptId, requestGate]);

  useEffect(() => {
    requestGate.activate(attemptId);
    setReport(null); setExpanded(null); setView(focusQuestionId ? 'answer' : 'statistics'); load();
    return () => requestGate.invalidate();
  }, [load, requestGate]);

  const loadedAttemptId = report?.attempt.id;
  useEffect(() => {
    if (report && !focusQuestionId) setExpanded(report.questions[0]?.id ?? null);
  }, [loadedAttemptId, focusQuestionId]);

  // Fires for both queued and persisted deliveries; re-read report + count.
  useEffect(() => {
    const onUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{ attemptId?: string }>).detail;
      if (detail?.attemptId && detail.attemptId !== attemptId) return;
      refreshPending();
      load();
    };
    window.addEventListener('toeic:interruption-updated', onUpdated);
    return () => window.removeEventListener('toeic:interruption-updated', onUpdated);
  }, [attemptId, load, refreshPending]);

  // Explicit deep links select the immutable question, independent of its number.
  useEffect(() => {
    if (!report || report.attempt.id !== attemptId || !focusQuestionId) return;
    setView('answer'); setExpanded(focusQuestionId);
  }, [loadedAttemptId, focusQuestionId, attemptId]);

  const workspace = useMemo(() => report ? reviewWorkspace(report, snapshot) : null, [report, snapshot]);
  const answers = useMemo(() => Object.fromEntries(Object.entries(workspace?.answers ?? {})
    .map(([id, answer]) => [id, { ...answer, dirty: false }])), [workspace]);

  if (error) {
    return (
      <div className="page">
        <ErrorBlock message={error} onRetry={load} />
        <button type="button" className="btn btn-secondary" onClick={onBack}>
          返回
        </button>
      </div>
    );
  }

  if (!report || report.attempt.id !== attemptId) {
    return (
      <div className="page">
        <Loading label="正在读取报告…" />
      </div>
    );
  }

  const currentIndex = reviewFocusIndex(report, expanded);
  const question = report.questions[currentIndex];
  const group = report.groups.find((item) => item.id === question?.group_id);
  const reviewQueue = workspace?.audio_queue ?? [];
  const jumpTo = (index: number) => setExpanded(report.questions[index]?.id ?? null);

  // A retake rebuilds THIS report's scope, never an unrelated last selection.
  const handleExactRetake = async () => {
    if (!report || retaking) return;
    setRetaking(true); setRetakeError(null);
    try {
      const attempt = await api.createAttempt({
        scope: report.attempt.scope, mode: report.attempt.mode,
        timer: { kind: report.attempt.timer_config?.kind ?? (report.attempt.mode === 'exam' ? 'countdown' : 'none'),
          ...(report.attempt.timer_config?.duration_seconds ? { duration_seconds: report.attempt.timer_config.duration_seconds } : {}) },
        retake_attempt_id: attemptId,
      });
      onOpenAttempt(attempt.id);
    } catch (cause) { setRetakeError(cause instanceof Error ? cause.message : '精确重做失败。'); }
    finally { setRetaking(false); }
  };

  return (
    <div className="page page-report" data-testid="report-screen">
      <header className="page-head">
        <div>
          <p className="eyebrow">交卷报告</p>
          <h1>{practiceTitle(report.attempt.scope, report.attempt.created_at ?? new Date().toISOString())}</h1>
          <p className="page-sub">
            {SCOPE_LABEL[report.attempt.scope]} · {MODE_LABEL[report.attempt.mode]} ·{' '}
            {pendingInterruptions > 0 ? (
              // Pending delivery outranks a durable record: the header must not
              // claim a clean run while an event is still being saved.
              <Tag tone="warn">中断记录待确认</Tag>
            ) : report.attempt.interruptions.length > 0 ? (
              <Tag tone="warn">存在中断记录</Tag>
            ) : (
              '计时完整'
            )}
          </p>
        </div>
        <div className="page-actions">
          <div className="workspace-view-count"><WorkspaceViewToggle view={view} onChange={setView} />
            <span className="sticky-stat">已答 {report.summary.total - report.summary.unanswered}/{report.summary.total}</span></div>
          <button type="button" className="btn btn-secondary" onClick={onBack}>
            返回练习
          </button>
          <button type="button" className="btn btn-secondary" onClick={onRetake} data-testid="new-random-button">
            新随机练习
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void handleExactRetake()} disabled={retaking} data-testid="retake-button">
            {retaking ? '正在创建…' : '按原题序精确重做'}
          </button>
        </div>
      </header>
      {retakeError ? <Banner tone="error" title="精确重做失败">{retakeError}</Banner> : null}

      <div hidden={view !== 'statistics'} className="report-statistics">
      <section className="summary-grid" aria-label="成绩摘要">
        <Stat label="正确率" value={percent(report.summary.correct_percent)} note={`${report.summary.correct} / ${report.summary.total} 题`} />
        <Stat label="正确" value={report.summary.correct} note={percent(report.summary.correct_percent)} />
        <Stat label="错误" value={report.summary.wrong} note={percent(report.summary.wrong_percent)} />
        <Stat label="未做" value={report.summary.unanswered} note={percent(report.summary.unanswered_percent)} />
        <Stat
          label="已答正确率"
          value={report.summary.answered_accuracy === null ? '—' : percent(report.summary.answered_accuracy)}
          note="正确 /（正确 + 错误）"
        />
      </section>
      <ActivityStatistics activity={report.activity} />

      {report.summary.by_part.length > 0 ? (
        <section className="part-table" aria-label="分区统计">
          <h2>分区表现</h2>
          <table>
            <thead>
              <tr>
                <th scope="col">Part</th>
                <th scope="col">题数</th>
                <th scope="col">正确</th>
                <th scope="col">错误</th>
                <th scope="col">未做</th>
                <th scope="col">正确率</th>
              </tr>
            </thead>
            <tbody>
              {report.summary.by_part.map((row) => (
                <tr key={row.part}>
                  <th scope="row">{PART_LABEL[row.part] ?? `Part ${row.part}`}</th>
                  <td>{row.total}</td>
                  <td>{row.correct}</td>
                  <td>{row.wrong}</td>
                  <td>{row.unanswered}</td>
                  <td>{percent(row.correct_percent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      </div>
      {pendingInterruptions > 0 ? (
        <Banner tone="warn" title="中断记录待确认，暂不视为有效模拟" data-testid="pending-interruption-banner">
          还有 {pendingInterruptions} 条中断记录正在保存。保存完成后会显示最终结果，成绩不会因此改变。
        </Banner>
      ) : null}
      <UnscoredDrafts attemptId={attemptId} questions={report.questions} />
      <section className="workspace-body review-workspace" hidden={view !== 'answer'} aria-label="逐题复盘">
        <main className="workspace-main">
          {reviewQueue.length > 0 && !report.groups.some((item) => item.review_audio) ? (
            <details className="legacy-audio"><summary>历史记录的整段音轨</summary>
              <ReviewAudioBar queue={reviewQueue} focusQuestionId={question?.id} />
            </details>
          ) : null}
          {question && group && workspace ? <div data-review-id={question.id} data-testid={`review-${question.id}`}>
            {group.section === 'listening' ? <ListeningReview key={`${attemptId}:${group.id}`} group={group} /> : null}
            <QuestionPanel question={question} group={group} answer={answers[question.id]} readOnly attempt={workspace}
              onSelect={() => undefined} onFlag={() => undefined} solution={{ answer: question.answer, selected: question.selected_option_id }} />
            <ReviewDetails key={`${attemptId}:${question.id}`} question={question} group={group} attemptId={attemptId}
              integrity={report.attempt.integrity} status={report.attempt.status} onReviewed={load} />
          </div> : <p className="answer-empty">本轮没有可复盘的题目。</p>}
          <div className="nav-row">
            <button type="button" className="btn btn-secondary" disabled={currentIndex === 0} onClick={() => jumpTo(currentIndex - 1)}>上一题</button>
            <span className="nav-position">本轮第 {question ? currentIndex + 1 : 0} / {report.questions.length} 题 · 只读复盘</span>
            <button type="button" className="btn btn-secondary" disabled={currentIndex >= report.questions.length - 1} onClick={() => jumpTo(currentIndex + 1)}>下一题</button>
          </div>
        </main>
        {workspace ? <AnswerCard attempt={workspace} answers={answers} currentIndex={currentIndex} onJump={jumpTo}
          results={Object.fromEntries(report.questions.map((item) => [item.id, item.result]))} /> : null}
      </section>
    </div>
  );
}

function ReviewDetails({ question, group, attemptId, integrity, status, onReviewed }: {
  question: ReportQuestion; group: AttemptReport['groups'][number]; attemptId: string;
  integrity?: 'valid' | 'interrupted'; status: string; onReviewed: () => void;
}) {
  const note = erratumNote(question);
  return <div className="review-details">
    <ResultTag result={question.result} />
    {note ? <div className="erratum-note" data-testid={`erratum-${question.id}`} role="note">{note.text}</div> : null}
          {question.explanation && question.section === 'listening' ? (
            <details className="explanation source-explanation" data-testid="original-explanation">
              <summary>查看解析与补充表达</summary>
              <p>{question.explanation.text}</p>
              {group?.review_text ? <p>{group.review_text}</p> : null}
            </details>
          ) : question.explanation ? (
            <div className="explanation">
              <h4>解析</h4>
              <p>{question.explanation.text}</p>
            </div>
          ) : null}

          {group?.review_text && question.section !== 'listening' ? (
            <div className="explanation">
              <h4>原文 / 译文</h4>
              <p>{group.review_text}</p>
            </div>
          ) : null}

          {(() => {
            const eligibility = reviewEligibility({
              result: question.result,
              integrity: integrity,
              status: status,
            });
            if (eligibility.allowed) {
              return <ErrorReview question={question} attemptId={attemptId} onReviewed={onReviewed} />;
            }
            if (eligibility.reason) {
              return (
                <p className="phase-note" data-testid={`review-blocked-${question.id}`}>
                  {eligibility.reason}
                </p>
              );
            }
            return null;
          })()}
  </div>;
}

function ResultTag({ result }: { result: ReportQuestion['result'] }) {
  if (result === 'correct') return <Tag tone="good">正确</Tag>;
  if (result === 'wrong') return <Tag tone="bad">错误</Tag>;
  return <Tag tone="neutral">未做</Tag>;
}

function ErrorReview({
  question,
  attemptId,
  onReviewed,
}: {
  question: ReportQuestion;
  attemptId: string;
  onReviewed: () => void;
}) {
  const [causes, setCauses] = useState<ReviewCause[]>(question.review?.causes ?? []);
  const [words, setWords] = useState<ReviewWord[]>(question.review?.words ?? []);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [freeform, setFreeform] = useState('');
  const [sense, setSense] = useState('');
  const [modality, setModality] = useState<'meaning' | 'listening'>('meaning');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .candidates(attemptId, question.id)
      .then((response) => active && setCandidates(response.candidates))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [attemptId, question.id]);

  const vocabRelated = causes.includes('meaning') || causes.includes('listening');

  const toggleCause = (cause: ReviewCause) => {
    setCauses((prev) => (prev.includes(cause) ? prev.filter((item) => item !== cause) : [...prev, cause]));
  };

  const addWord = (term: string) => {
    const clean = term.trim();
    if (!clean) return;
    setWords((prev) =>
      prev.some((item) => item.term.toLowerCase() === clean.toLowerCase())
        ? prev
        : [...prev, { term: clean, sense, modality, causal: true }],
    );
    setFreeform('');
  };

  const removeWord = (term: string) => {
    setWords((prev) => prev.filter((item) => item.term !== term));
  };

  const updateWord = (term: string, patch: Partial<ReviewWord>) => {
    setWords((prev) => prev.map((item) => (item.term === term ? { ...item, ...patch } : item)));
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await api.saveReview(attemptId, question.id, { causes, words });
      setMessage(causes.length === 0 && words.length === 0 ? '已清空该题错因与词汇证据。' : '已保存。');
      onReviewed();
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : '保存失败。');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="error-review" data-testid={`error-review-${question.id}`}>
      <h4>错因与生词</h4>
      <div className="cause-grid" role="group" aria-label="错因">
        {CAUSES.map((cause) => (
          <label key={cause} className="cause-chip" data-active={causes.includes(cause)}>
            <input
              type="checkbox"
              checked={causes.includes(cause)}
              onChange={() => toggleCause(cause)}
              data-testid={`cause-${question.id}-${cause}`}
            />
            <span>{CAUSE_LABEL[cause]}</span>
          </label>
        ))}
      </div>

      {vocabRelated ? (
        <div className="vocab-evidence">
          <div className="word-meta-row">
            <label>
              <span>词义/用法</span>
              <input
                type="text"
                value={sense}
                onChange={(event) => setSense(event.target.value)}
                placeholder="可留空"
                data-testid={`sense-${question.id}`}
              />
            </label>
            <label>
              <span>类型</span>
              <select value={modality} onChange={(event) => setModality(event.target.value as 'meaning' | 'listening')}>
                <option value="meaning">词义</option>
                <option value="listening">听辨</option>
              </select>
            </label>
          </div>
          <p className="vocab-hint">先填写词义/用法和类型，再选择词；已选中的词也可以单独修改。</p>
          {candidates.length > 0 ? (
            <div className="candidate-row">
              <span className="candidate-label">候选词</span>
              <div className="candidate-chips">
                {candidates.slice(0, 20).map((candidate) => (
                  <button
                    key={candidate.term}
                    type="button"
                    className="candidate-chip"
                    onClick={() => addWord(candidate.term)}
                    title={candidate.context}
                    data-testid={`candidate-${question.id}-${candidate.term}`}
                  >
                    {candidate.term}
                    <span className="candidate-count">{candidate.count}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="freeform-row">
            <input
              type="text"
              value={freeform}
              placeholder="或手动输入词/短语"
              aria-label="添加造成错误的词或短语"
              onChange={(event) => setFreeform(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  addWord(freeform);
                }
              }}
              data-testid={`freeform-${question.id}`}
            />
            <button type="button" className="btn btn-secondary" onClick={() => addWord(freeform)}>
              添加
            </button>
          </div>
          {words.length > 0 ? (
            <ul className="word-list">
              {words.map((word) => (
                <li key={word.term}>
                  <span className="word-term">{word.term}</span>
                  <input
                    className="word-sense-input"
                    type="text"
                    value={word.sense}
                    placeholder="补充词义/用法"
                    aria-label={`${word.term} 的词义或用法`}
                    onChange={(event) => updateWord(word.term, { sense: event.target.value })}
                    data-testid={`word-sense-${question.id}-${word.term}`}
                  />
                  <select
                    className="word-modality"
                    value={word.modality}
                    onChange={(event) =>
                      updateWord(word.term, { modality: event.target.value as 'meaning' | 'listening' })
                    }
                    aria-label={`${word.term} 的类型`}
                  >
                    <option value="meaning">词义</option>
                    <option value="listening">听辨</option>
                  </select>
                  <button type="button" className="link-btn" onClick={() => removeWord(word.term)}>
                    撤回
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <p className="vocab-hint">选择“词义不懂”或“认识但没听出”后，可确认造成错误的词。</p>
      )}

      <div className="review-actions">
        <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving} data-testid={`save-review-${question.id}`}>
          {saving ? '保存中…' : '保存错因'}
        </button>
        {message ? <span className="review-message">{message}</span> : null}
      </div>
    </div>
  );
}

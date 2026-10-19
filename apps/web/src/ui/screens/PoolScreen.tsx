import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import type { PoolQuestionStatus, QuestionPoolQuestionDetail, QuestionPoolStatusResponse } from '../../domain/types';
import { PART_LABEL } from '../../domain/format';
import { Banner, EmptyBlock, ErrorBlock, Loading, Tag } from '../components';
import { navigate } from '../router';
import { MaterialContent, MarkdownText, MarkdownInline } from '../MaterialContent';
import { pageSlice } from './poolPagination';
import { PoolDetailModal } from './PoolDetailModal';
import { ReviewAudioBar } from './ReviewAudioBar';
import { TranscriptPanel } from '../TranscriptPanel';
import { matchesPoolFilter, type PoolQuestionFilter } from './poolQuestionFilter';

const STATUS_LABEL: Record<PoolQuestionStatus, string> = { answered: '已作答', unanswered: '未作答', wrong: '错题' };

export function PoolScreen({ questionId }: { questionId?: string }) {
  const [summary, setSummary] = useState<QuestionPoolStatusResponse | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusRetry, setStatusRetry] = useState(0);
  const [detail, setDetail] = useState<QuestionPoolQuestionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [includeSolution, setIncludeSolution] = useState(false);
  const [listFilter, setListFilter] = useState<PoolQuestionFilter>('all');
  const detailRequestId = useRef(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);

  useEffect(() => {
    let active = true;
    setLoading(true); setSummaryError(null);
    api.questionPoolStatus().then((result) => { if (active) setSummary(result); })
      .catch((cause: unknown) => { if (active) setSummaryError(cause instanceof Error ? cause.message : '题库状态读取失败。'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [statusRetry]);

  useEffect(() => {
    let active = true;
    const loadMasked = () => {
      const requestId = ++detailRequestId.current;
      // Re-entering this tab always discards previously revealed content before
      // checking the server's current strict-exam lock.
      setIncludeSolution(false); setDetail(null); setDetailError(null);
      if (!questionId) { setDetailLoading(false); return; }
      setDetailLoading(true);
      api.questionPoolQuestion(questionId, false)
        .then((result) => { if (active && requestId === detailRequestId.current) setDetail(result); })
        .catch((cause: unknown) => { if (active && requestId === detailRequestId.current) setDetailError(detailMessage(cause)); })
        .finally(() => { if (active && requestId === detailRequestId.current) setDetailLoading(false); });
    };
    const onVisible = () => { if (document.visibilityState === 'visible') loadMasked(); };
    loadMasked();
    window.addEventListener('focus', loadMasked);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      active = false; detailRequestId.current++;
      window.removeEventListener('focus', loadMasked);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [questionId]);

  async function toggleSolution() {
    if (!questionId || detailLoading) return;
    const requestId = ++detailRequestId.current;
    const next = !includeSolution;
    if (!next) setIncludeSolution(false);
    setDetailLoading(true); setDetailError(null);
    try {
      const result = await api.questionPoolQuestion(questionId, next);
      if (requestId === detailRequestId.current) { setDetail(result); setIncludeSolution(next); }
    } catch (cause) {
      if (requestId === detailRequestId.current) { setIncludeSolution(false); setDetail(null); setDetailError(detailMessage(cause)); }
    } finally { if (requestId === detailRequestId.current) setDetailLoading(false); }
  }

  const question = detail?.question.id === questionId ? detail?.question : undefined;
  const group = detail?.question.id === questionId ? detail?.group : undefined;
  const protectedPart = question?.part === 1 || question?.part === 2;
  const visibleQuestions = summary?.questions.filter((item) => matchesPoolFilter(item.status, listFilter)) ?? [];
  const pagination = pageSlice(visibleQuestions, page, pageSize);

  return <div className="page page-pool" data-testid="pool-screen">
    <header className="page-head"><div><p className="eyebrow">题库</p><h1>题目总览</h1>
      <p className="page-sub">按最近一次有效的已结束作答统计。错题是已作答题目中的子集；所有百分比均以全部题库题目为分母。</p></div></header>
    {loading && <Loading label="正在读取题库状态…" />}
    {summaryError && <ErrorBlock message={summaryError} onRetry={() => setStatusRetry((value) => value + 1)} />}
    {summary && <>
      <section className="summary-grid pool-summary" aria-label="题库学习状态">
        <PoolStat label="题库总量" value={summary.total} note={`题库版本 ${summary.library_version}`} />
        <PoolStat label="已作答" value={summary.answered} percent={summary.answered_percent} denominator={summary.total} />
        <PoolStat label="未作答" value={summary.unanswered} percent={summary.unanswered_percent} denominator={summary.total} />
        <PoolStat label="错题" value={summary.wrong} percent={summary.wrong_percent} denominator={summary.total} note="已作答题目子集" />
      </section>
      <div className="pool-layout">
        <section className="pool-list-panel" aria-label="题库题目列表">
          <div className="section-head"><h2 tabIndex={-1}>{listFilter === 'all' ? '全部题目' : listFilter === 'unanswered' ? '未作答' : listFilter === 'answered' ? '已做' : '错题'}（{visibleQuestions.length} / {summary.total}）</h2></div>
          <div className="chip-row pool-filters" role="group" aria-label="题库状态筛选">{([
            ['all', '全部'], ['unanswered', '未作答'], ['answered', '已做'], ['wrong', '错题'],
          ] as Array<[PoolQuestionFilter, string]>).map(([filter, label]) => <button key={filter} type="button" className="chip chip-compact" data-active={listFilter === filter} aria-pressed={listFilter === filter} onClick={() => { setListFilter(filter); setPage(1); }}>{label}</button>)}</div>
          <div className="pool-pagination">
            <span role="status">第 {pagination.page} / {pagination.pages} 页 · {visibleQuestions.length} 题</span>
            <label>每页 <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>
              <option value={50}>50 题</option><option value={100}>100 题</option><option value={200}>200 题</option>
            </select></label>
            <button type="button" className="btn btn-secondary" disabled={pagination.page <= 1} onClick={() => setPage(pagination.page - 1)}>上一页</button>
            <button type="button" className="btn btn-secondary" disabled={pagination.page >= pagination.pages} onClick={() => setPage(pagination.page + 1)}>下一页</button>
          </div>
          {visibleQuestions.length === 0 ? <EmptyBlock title="没有符合条件的题目" /> : <div className="pool-card-grid">
            {pagination.items.map((item) => <button key={item.id} type="button" className="answer-cell pool-cell"
              data-state={item.status === 'unanswered' ? 'untouched' : 'answered'} data-result={item.status}
              data-current={item.id === questionId} aria-haspopup="dialog"
              aria-label={`打开题库第 ${item.number} 题，Part ${item.part}，${STATUS_LABEL[item.status]}`}
              onClick={() => navigate({ name: 'pool', questionId: item.id })}>
              <span className="cell-index">{item.number}</span>
            </button>)}
          </div>}
        </section>
      </div>
    </>}
    {questionId ? <PoolDetailModal key={questionId} onClose={() => navigate({ name: 'pool' })}>
          {questionId && detailLoading && (!detail || detail.question.id !== questionId) && <Loading label="正在读取题目详情…" />}
          {questionId && detailError && <Banner tone="warn" title="暂时无法显示详情">{detailError}</Banner>}
          {question && group && <>
            <div className="pool-detail-head"><div><p className="eyebrow">{PART_LABEL[question.part]} · 题库序号 {question.number}</p><h3>题目内容</h3></div>
              <Tag tone={detail!.status === 'wrong' ? 'bad' : detail!.status === 'answered' ? 'good' : 'neutral'}>{STATUS_LABEL[detail!.status]}</Tag>
            </div>
            {detailLoading && <Loading label={includeSolution ? '正在读取完整解析…' : '正在隐藏完整解析…'} />}
            {!includeSolution && protectedPart ? <Banner tone="info" title="听力作答内容已保护">Part 1 和 Part 2 的题干与选项文本仅在你主动显示完整解析时展开。</Banner> : <MarkdownText className="pool-question-stem" text={question.stem || '题干内容暂不可用。'} flow="prose" />}
            {!includeSolution && protectedPart ? <p className="pool-masked">题干与选项文本已隐藏</p> : <ol className="option-review pool-options">
              {question.options.map((option) => <li key={option.id}><span className="option-key">{option.id}</span><MarkdownInline className="option-text" text={option.text || `选项 ${option.id}`} />
                {includeSolution && question.answer === option.id ? <Tag tone="good">正确答案</Tag> : null}</li>)}
            </ol>}
            <MaterialContent materials={group.materials} questionNumbers={Object.fromEntries((summary?.questions ?? []).map(q => [q.id, q.number]))} />
            {includeSolution && question.explanation ? <section className="explanation"><h3>解析</h3><MarkdownText text={question.explanation.text} /></section> : null}
            {includeSolution && group.review_text ? <section className="explanation"><h3>补充说明</h3><MarkdownText text={group.review_text} /></section> : null}
            {includeSolution && group.review_audio ? <ReviewAudioBar queue={[group.review_audio]} label="本组听力" replayLabel="重放本组" renderTranscript={(audio, clip) => group.listening_script ? <TranscriptPanel script={group.listening_script} clip={clip} sourceTime={(clip?.start_seconds ?? 0) + audio.state.positionSeconds} onSentence={(sourceTime) => void audio.playSentence(sourceTime)} /> : null} /> : null}
            {includeSolution && group.listening_script && !group.review_audio ? <TranscriptPanel script={group.listening_script} /> : null}
            {detail!.solution_available && <button type="button" className="btn btn-primary" disabled={detailLoading} onClick={() => void toggleSolution()} data-testid="pool-solution-toggle">{includeSolution ? '隐藏完整解析' : '显示完整解析'}</button>}
            {!detail!.solution_available && <p className="phase-note">模拟进行中，交卷后可查看完整解析</p>}
          </>}
    </PoolDetailModal> : null}
  </div>;
}

function PoolStat({ label, value, percent, denominator, note }: { label: string; value: number; percent?: number; denominator?: number; note?: string }) {
  return <div className="stat"><span className="stat-label">{label}</span><strong className="stat-value">{value}</strong>
    {percent !== undefined && <span className="stat-note">{percent.toFixed(2)}% · 全部 {denominator} 题</span>}
    {note && <span className="stat-note">{note}</span>}
  </div>;
}

function detailMessage(cause: unknown): string {
  if (cause instanceof ApiError && cause.status === 409 && cause.code === 'solutions_locked') {
    return '严格模拟进行期间，题目详情或完整解析暂不可查看。结束模拟后可返回此处查看。';
  }
  return cause instanceof Error ? cause.message : '题目详情读取失败。';
}

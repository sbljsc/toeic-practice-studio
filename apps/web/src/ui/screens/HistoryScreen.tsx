import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import { MODE_LABEL, SCOPE_LABEL, formatDateTime, percent, practiceTitle } from '../../domain/format';
import type { AttemptSummary, AttemptStatus } from '../../domain/types';
import { EmptyBlock, ErrorBlock, Loading, Stat, Tag } from '../components';

interface Props {
  onOpenAttempt: (id: string) => void;
  onOpenReport: (id: string) => void;
  initialFilter?: 'wrong' | null;
}

interface HistoryItem extends AttemptSummary {
  summary?: {
    correct: number;
    wrong: number;
    unanswered: number;
    correct_percent: number;
  };
}

export function HistoryScreen({ onOpenAttempt, onOpenReport, initialFilter }: Props) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<'open' | 'closed' | 'all'>('all');
  const [resultFilter, setResultFilter] = useState<'all' | 'wrong' | 'correct' | 'none'>(
    initialFilter === 'wrong' ? 'wrong' : 'all',
  );
  const [statistics, setStatistics] = useState<{
    attempt_count: number;
    completed_count: number;
    by_part: Array<{ part: number; total: number; correct: number; wrong: number; unanswered: number; correct_percent: number }>;
  } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .listAttempts()
      .then((response) => {
        setItems(response.attempts as HistoryItem[]);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof ApiError ? cause.message : '读取历史失败。');
        setLoading(false);
      });
    api
      .statistics()
      .then((response) =>
        setStatistics({
          attempt_count: response.attempt_count,
          completed_count: response.completed_count,
          by_part: response.by_part,
        }),
      )
      .catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  const visible = items.filter((item) => {
    const closed = item.status === 'submitted' || item.status === 'expired';
    if (statusFilter === 'open' && closed) return false;
    if (statusFilter === 'closed' && !closed) return false;
    if (resultFilter === 'none') return item.summary === undefined;
    if (resultFilter === 'wrong') return (item.summary?.wrong ?? 0) > 0;
    if (resultFilter === 'correct') return item.summary !== undefined &&
      item.summary.correct === item.question_count && item.summary.wrong === 0 && item.summary.unanswered === 0;
    return true;
  });

  return (
    <div className="page page-history" data-testid="history-screen">
      <header className="page-head">
        <div>
          <p className="eyebrow">历史</p>
          <h1>练习记录</h1>
          <p className="page-sub">记录只读。重做会创建新的练习记录，不会覆盖旧成绩。</p>
        </div>
      </header>

      {statistics ? (
        <section className="summary-grid" aria-label="总体统计">
          <Stat label="总轮次" value={statistics.attempt_count} />
          <Stat label="已完成" value={statistics.completed_count} />
          <Stat
            label="有效模拟 Part"
            value={statistics.by_part.length}
            note={statistics.by_part.map((row) => `P${row.part}`).join(' ')}
          />
        </section>
      ) : null}

      <div className="filter-row" role="group" aria-label="历史筛选">
        {(
          [
            { key: 'all', label: '全部状态' },
            { key: 'open', label: '进行中' },
            { key: 'closed', label: '已结束' },
          ] as const
        ).map((item) => (
          <button
            key={item.key}
            type="button"
            className="chip chip-compact"
            data-active={statusFilter === item.key}
            onClick={() => setStatusFilter(item.key)}
          >
            {item.label}
          </button>
        ))}
        <span className="filter-divider" aria-hidden="true" />
        {(
          [
            { key: 'all', label: '全部结果' },
            { key: 'wrong', label: '有错题' },
            { key: 'correct', label: '全对' },
            { key: 'none', label: '未评分' },
          ] as const
        ).map((item) => (
          <button
            key={item.key}
            type="button"
            className="chip chip-compact"
            data-active={resultFilter === item.key}
            onClick={() => setResultFilter(item.key)}
            data-testid={`history-filter-${item.key}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {loading ? <Loading label="正在读取历史…" /> : null}
      {error ? <ErrorBlock message={error} onRetry={load} /> : null}
      {!loading && !error && visible.length === 0 ? (
        <EmptyBlock title="没有符合条件的记录" hint="完成一轮练习后会出现在这里。" />
      ) : null}

      <ul className="history-list">
        {visible.map((item) => {
          const closed = item.status === 'submitted' || item.status === 'expired';
          return (
            <li key={item.id} className="history-row" data-testid={`history-${item.id}`}>
              <div className="history-main">
                <div className="history-title-row">
                  <strong>{practiceTitle(item.scope, item.created_at)}</strong>
                  <StatusTag status={item.status} />
                </div>
                <p className="history-meta">
                  {SCOPE_LABEL[item.scope]} · {MODE_LABEL[item.mode]} · {item.question_count} 题 · 已答{' '}
                  {item.answered_count} · {formatDateTime(item.created_at)}
                </p>
                {item.summary ? (
                  <p className="history-result">
                    正确 {item.summary.correct} · 错误 {item.summary.wrong} · 未做 {item.summary.unanswered} ·{' '}
                    {percent(item.summary.correct_percent)}
                  </p>
                ) : null}
              </div>
              <div className="history-actions">
                {closed ? (
                  <button type="button" className="btn btn-secondary" onClick={() => onOpenReport(item.id)}>
                    报告
                  </button>
                ) : (
                  <button type="button" className="btn btn-primary" onClick={() => onOpenAttempt(item.id)}>
                    继续
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function StatusTag({ status }: { status: AttemptStatus }) {
  const map: Record<AttemptStatus, { label: string; tone: 'neutral' | 'good' | 'warn' | 'bad' | 'info' }> = {
    ready: { label: '未开始', tone: 'neutral' },
    running: { label: '进行中', tone: 'info' },
    paused: { label: '已暂停', tone: 'warn' },
    submitted: { label: '已交卷', tone: 'good' },
    expired: { label: '已过期', tone: 'bad' },
  };
  const item = map[status];
  return <Tag tone={item.tone}>{item.label}</Tag>;
}

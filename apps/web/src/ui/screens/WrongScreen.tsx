import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import { PART_LABEL } from '../../domain/format';
import type { AttemptReport } from '../../domain/types';
import { Banner, EmptyBlock, ErrorBlock, Loading, Tag } from '../components';
import { navigate } from '../router';
import { aggregateWrongAnswers } from './wrongAggregate';
import { MarkdownText } from '../MaterialContent';

// The wrong book spans ALL graded history, not just the latest report. A
// question leaves the book only when a later graded attempt answers it
// correctly. Unanswered questions are never listed as wrong answers.
export function WrongScreen() {
  const [entries, setEntries] = useState<ReturnType<typeof aggregateWrongAnswers>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partFilter, setPartFilter] = useState<number | 'all'>('all');
  const [partial, setPartial] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setPartial(null);
    api
      .listAttempts()
      .then(async (response) => {
        const graded = response.attempts.filter(
          (item) => item.status === 'submitted' || item.status === 'expired',
        );
        if (graded.length === 0) {
          setEntries([]);
          setLoading(false);
          return;
        }
        const meta: Record<string, { id: string; title: string; created_at: string }> = {};
        for (const item of graded) {
          meta[item.id] = { id: item.id, title: item.title, created_at: item.created_at };
        }
        const settled = await Promise.allSettled(graded.map((item) => api.report(item.id)));
        const reports: AttemptReport[] = [];
        const failed: string[] = [];
        settled.forEach((outcome, index) => {
          if (outcome.status === 'fulfilled') reports.push(outcome.value);
          else failed.push(graded[index].id);
        });
        setEntries(aggregateWrongAnswers(reports, meta));
        // Report honestly when only part of the history could be read.
        setPartial(failed.length > 0 ? `${failed.length} 条历史记录读取失败，错题可能不完整。` : null);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof ApiError ? cause.message : '读取错题失败。');
        setLoading(false);
      });
  }, []);

  useEffect(load, [load]);

  const visible = partFilter === 'all' ? entries : entries.filter((entry) => entry.question.part === partFilter);

  return (
    <div className="page page-wrong" data-testid="wrong-screen">
      <header className="page-head">
        <div>
          <p className="eyebrow">错题</p>
          <h1>错题本</h1>
          <p className="page-sub">
            汇总有效已交卷记录里最近一次实际作答仍然错误的题。重新做对后会自动移出；想优先练这些题，请在练习中选择“错题优先”。
          </p>
        </div>
      </header>

      {loading ? <Loading label="正在读取错题…" /> : null}
      {error ? <ErrorBlock message={error} onRetry={load} /> : null}
      {partial ? <Banner tone="warn" title="部分历史未能读取">{partial}</Banner> : null}

      {!loading && !error && entries.length === 0 ? (
        <EmptyBlock title="没有待解决的错题" hint="交卷后做错的题会自动出现在这里。" />
      ) : null}

      {entries.length > 0 ? (
        <>
          <Banner tone="info" title="关于这份错题本">
            共 {entries.length} 道待解决。这里只显示做错的题；没做的题不算错题。
          </Banner>
          <div className="filter-row" role="group" aria-label="按 Part 筛选">
            <button
              type="button"
              className="chip chip-compact"
              data-active={partFilter === 'all'}
              onClick={() => setPartFilter('all')}
            >
              全部 ({entries.length})
            </button>
            {[1, 2, 3, 4, 5, 6, 7].map((part) => {
              const count = entries.filter((entry) => entry.question.part === part).length;
              if (count === 0) return null;
              return (
                <button
                  key={part}
                  type="button"
                  className="chip chip-compact"
                  data-active={partFilter === part}
                  onClick={() => setPartFilter(part)}
                  data-testid={`wrong-part-${part}`}
                >
                  P{part} ({count})
                </button>
              );
            })}
          </div>
        </>
      ) : null}

      {visible.length === 0 && entries.length > 0 ? <EmptyBlock title="该 Part 没有待解决的错题" /> : null}

      <ul className="wrong-list">
        {visible.map((entry) => (
          <li key={`${entry.attemptId}-${entry.question.id}`} className="wrong-row" data-result="wrong">
            <div className="wrong-main">
              <div className="wrong-head">
                <Tag tone="neutral">{PART_LABEL[entry.question.part] ?? `Part ${entry.question.part}`}</Tag>
                <span>Part {entry.question.part}</span>
                <Tag tone="bad">错误</Tag>
                {entry.wrongCount > 1 ? <Tag tone="warn">错 {entry.wrongCount} 次</Tag> : null}
                {entry.fixedCount > 0 ? <Tag tone="good">曾做对 {entry.fixedCount} 次</Tag> : null}
              </div>
              <MarkdownText className="wrong-stem" text={entry.question.stem || '题目'} flow="prose" />
              <p className="wrong-answer">
                上次你的答案 {entry.question.selected_option_id ?? '未做'} · 正确答案 {entry.question.answer}
              </p>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigate({ name: 'report', id: entry.attemptId, focusQuestionId: entry.question.id })}
              data-testid={`wrong-review-${entry.question.id}`}
            >
              复盘
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

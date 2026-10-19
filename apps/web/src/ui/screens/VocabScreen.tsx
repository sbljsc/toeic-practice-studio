import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import { VOCAB_STATUS_LABEL } from '../../domain/format';
import type { VocabEntry, VocabStatus } from '../../domain/types';
import { Banner, EmptyBlock, ErrorBlock, Loading, Tag } from '../components';
import { navigate } from '../router';
import { MarkdownText, MarkdownInline } from '../MaterialContent';

type StatusFilter = 'all' | VocabStatus;

export function VocabScreen() {
  const [entries, setEntries] = useState<VocabEntry[]>([]);
  const [threshold, setThreshold] = useState(3);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .vocabulary()
      .then((response) => {
        setEntries(response.entries);
        setThreshold(response.threshold);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof ApiError ? cause.message : '读取生词失败。');
        setLoading(false);
      });
  }, []);

  useEffect(load, [load]);

  const patch = async (id: string, body: { mastered?: boolean; manual_required?: boolean }) => {
    setBusyId(id);
    try {
      const response = await api.patchVocab(id, body);
      setEntries(response.entries);
      setThreshold(response.threshold);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '更新失败。');
    } finally {
      setBusyId(null);
    }
  };

  const visible = useMemo(
    () => (filter === 'all' ? entries : entries.filter((entry) => entry.status === filter)),
    [entries, filter],
  );

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: entries.length };
    for (const entry of entries) {
      map[entry.status] = (map[entry.status] ?? 0) + 1;
    }
    return map;
  }, [entries]);

  return (
    <div className="page page-vocab" data-testid="vocab-screen">
      <header className="page-head">
        <div>
          <p className="eyebrow">生词</p>
          <h1>因果生词本</h1>
          <p className="page-sub">
            只统计你确认造成错误的词。当前阈值：不同题目 ≥ {threshold} 题且 ≥ 2 个材料自动进入必背。
          </p>
        </div>
      </header>

      <Banner tone="info" title="怎么算重复">
        同一道题练多次也只算一次；同一个材料里反复出错会单独标出。之后把词标记为已掌握，不会改动以前的成绩。
      </Banner>

      <div className="filter-row" role="group" aria-label="生词状态筛选">
        {(
          [
            { key: 'all', label: '全部' },
            { key: 'must_learn', label: '必背' },
            { key: 'concentrated', label: '集中错误' },
            { key: 'candidate', label: '候选' },
            { key: 'mastered', label: '已掌握' },
          ] as Array<{ key: StatusFilter; label: string }>
        ).map((item) => (
          <button
            key={item.key}
            type="button"
            className="chip chip-compact"
            data-active={filter === item.key}
            onClick={() => setFilter(item.key)}
            data-testid={`vocab-filter-${item.key}`}
          >
            {item.label}
            {counts[item.key] ? <span className="chip-count">{counts[item.key]}</span> : null}
          </button>
        ))}
      </div>

      {loading ? <Loading label="正在读取生词…" /> : null}
      {error ? <ErrorBlock message={error} onRetry={load} /> : null}
      {!loading && !error && visible.length === 0 ? (
        <EmptyBlock title="还没有确认的生词" hint="在错题复盘中选择词汇类错因并确认具体词条后，会出现在这里。" />
      ) : null}

      <ul className="vocab-list">
        {visible.map((entry) => (
          <li key={entry.id} className="vocab-row" data-testid={`vocab-${entry.id}`}>
            <div className="vocab-main">
              <div className="vocab-head">
                <strong className="vocab-term">{entry.term}</strong>
                <StatusChip status={entry.status} />
                <Tag tone={entry.modality === 'listening' ? 'info' : 'neutral'}>
                  {entry.modality === 'listening' ? '听辨' : '词义'}
                </Tag>
                {entry.manual_required ? <Tag tone="warn">手动必背</Tag> : null}
              </div>
              {entry.sense ? <MarkdownText className="vocab-sense" text={entry.sense} flow="prose" /> : <p className="vocab-sense muted">未填写词义/用法</p>}
              <p className="vocab-counts">
                不同题目 {entry.question_count}/{entry.threshold} · 材料 {entry.material_count} · 历史复发{' '}
                {entry.lifetime_question_count}
                {entry.material_count <= 1 && entry.question_count >= entry.threshold ? (
                  <span className="vocab-concentrated"> · 同一材料集中错误</span>
                ) : null}
              </p>
              {entry.evidence.length > 0 ? (
                <details className="vocab-evidence-list">
                  <summary>查看 {entry.evidence.length} 条证据</summary>
                  <ul>
                    {entry.evidence.map((item) => (
                      <li key={`${item.attempt_id}-${item.question_id}`}>
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() =>
                            navigate({ name: 'report', id: item.attempt_id, focusQuestionId: item.question_id })
                          }
                        >
                          查看这条练习记录
                        </button>
                        {item.context ? <MarkdownInline className="evidence-context" text={item.context} /> : null}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
            <div className="vocab-actions">
              {entry.status !== 'mastered' ? (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busyId === entry.id}
                  onClick={() => void patch(entry.id, { mastered: true })}
                  data-testid={`master-${entry.id}`}
                >
                  标记已掌握
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busyId === entry.id}
                  onClick={() => void patch(entry.id, { mastered: false })}
                >
                  重新学习
                </button>
              )}
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busyId === entry.id}
                onClick={() => void patch(entry.id, { manual_required: !entry.manual_required })}
                data-testid={`manual-${entry.id}`}
              >
                {entry.manual_required ? '取消手动必背' : '手动必背'}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusChip({ status }: { status: VocabStatus }) {
  const tone = status === 'must_learn' ? 'bad' : status === 'concentrated' ? 'warn' : status === 'mastered' ? 'good' : 'neutral';
  return <Tag tone={tone}>{VOCAB_STATUS_LABEL[status]}</Tag>;
}

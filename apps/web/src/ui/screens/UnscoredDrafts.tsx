import { useEffect, useState } from 'react';
import { listDrafts, type PendingDraft } from '../../domain/drafts';
import { getTabId } from '../../domain/tab';
import { Banner } from '../components';
import type { ReportQuestion } from '../../domain/types';

/**
 * Unacknowledged answer drafts for a CLOSED attempt. Shown as explicitly
 * unscored: never injected into the grade, never replayed into a new attempt,
 * and never deleted on mount, so they survive reloads.
 */
export function UnscoredDrafts({
  attemptId,
  questions,
}: {
  attemptId: string;
  questions: ReportQuestion[];
}) {
  const [drafts, setDrafts] = useState<PendingDraft[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let active = true;
    // Read-only lookup scoped to this tab; nothing is written or cleared here.
    listDrafts(attemptId, getTabId())
      .then((found) => {
        if (active) setDrafts(found);
      })
      .catch(() => {
        // Draft storage unavailable: the report still renders normally.
      });
    return () => {
      active = false;
    };
  }, [attemptId]);

  if (drafts.length === 0 || dismissed) return null;

  const uniqueQuestions = new Set(drafts.map((draft) => draft.questionId));

  return (
    <div data-testid="unscored-drafts">
      <Banner
        tone="warn"
        title={`${drafts.length} 条未确认的答案未计分`}
        action={
          <button type="button" className="btn btn-secondary" onClick={() => setDismissed(true)}>
            知道了
          </button>
        }
      >
        <p>这些选择当时没有保存成功，不会计入本次成绩，也不会自动进入其他练习。</p>
        <ul className="unscored-list">
          {drafts.map((draft) => {
            const question = questions.find((item) => item.id === draft.questionId);
            return (
              <li key={`${draft.questionId}-${draft.mutationId}`}>
                <span className="unscored-label">
                  第 {question?.number ?? '—'} 题
                  {draft.optionId ? ` · 本机选择 ${draft.optionId}` : ' · 本机未选择'}
                  {draft.flagged ? ' · 已标记' : ''}
                </span>
              </li>
            );
          })}
        </ul>
        <p className="unscored-count">按题目归并后共 {uniqueQuestions.size} 道题。</p>
      </Banner>
    </div>
  );
}

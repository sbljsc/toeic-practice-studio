// Answer-card display filter. This only changes WHICH cells are shown; it never
// changes the attempt scope, the question set, or the jump target index.

export type AnswerCardFilter = 'all' | 'answered' | 'unanswered' | 'flagged' | 'current';

export const ANSWER_CARD_FILTERS: Array<{ key: AnswerCardFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'answered', label: '已答' },
  { key: 'unanswered', label: '未答' },
  { key: 'flagged', label: '已标记' },
  { key: 'current', label: '当前' },
];

export interface CellState {
  optionId: string | null;
  flagged: boolean;
  visited: boolean;
}

export interface CardEntry<T> {
  question: T;
  /** Original index in the full question list; jumps must keep using it. */
  index: number;
  state: CellState;
  isCurrent: boolean;
}

export function filterCounts<T>(entries: Array<CardEntry<T>>): Record<AnswerCardFilter, number> {
  const counts: Record<AnswerCardFilter, number> = {
    all: entries.length,
    answered: 0,
    unanswered: 0,
    flagged: 0,
    current: 0,
  };
  for (const entry of entries) {
    if (entry.state.optionId !== null) counts.answered += 1;
    else counts.unanswered += 1;
    if (entry.state.flagged) counts.flagged += 1;
    if (entry.isCurrent) counts.current += 1;
  }
  return counts;
}

export function matchesFilter<T>(entry: CardEntry<T>, filter: AnswerCardFilter): boolean {
  switch (filter) {
    case 'answered':
      return entry.state.optionId !== null;
    case 'unanswered':
      return entry.state.optionId === null;
    case 'flagged':
      return entry.state.flagged;
    case 'current':
      return entry.isCurrent;
    case 'all':
    default:
      return true;
  }
}

/**
 * Returns the visible subset while preserving each entry's original index, so
 * jumping to a cell still lands on the right question.
 */
export function visibleEntries<T>(entries: Array<CardEntry<T>>, filter: AnswerCardFilter): Array<CardEntry<T>> {
  return entries.filter((entry) => matchesFilter(entry, filter));
}

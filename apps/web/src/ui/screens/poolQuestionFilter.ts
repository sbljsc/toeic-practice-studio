import type { PoolQuestionStatus } from '../../domain/types';

export type PoolQuestionFilter = 'all' | 'unanswered' | 'answered' | 'wrong';

export function matchesPoolFilter(status: PoolQuestionStatus, filter: PoolQuestionFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'answered') return status === 'answered' || status === 'wrong';
  return status === filter;
}

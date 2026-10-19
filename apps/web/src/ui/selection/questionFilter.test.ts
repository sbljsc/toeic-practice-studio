import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveQuestionFilter, usesCompleteExamScope } from './questionFilter.ts';

test('a stale wrong/bookmarked choice cannot truncate a full or section mock', () => {
  for (const scope of ['full', 'listening', 'reading'] as const) {
    for (const filter of ['all', 'wrong', 'unanswered', 'bookmarked'] as const) {
      assert.equal(effectiveQuestionFilter('exam', scope, filter), 'all');
    }
    assert.equal(usesCompleteExamScope('exam', scope), true);
  }
});

test('targeted mocks and every practice scope retain the selected filter', () => {
  for (const filter of ['all', 'wrong', 'unanswered', 'bookmarked'] as const) {
    for (const scope of ['part', 'custom'] as const) {
      assert.equal(effectiveQuestionFilter('exam', scope, filter), filter);
    }
    for (const scope of ['full', 'listening', 'reading', 'part', 'custom'] as const) {
      assert.equal(effectiveQuestionFilter('practice', scope, filter), filter);
    }
  }
});

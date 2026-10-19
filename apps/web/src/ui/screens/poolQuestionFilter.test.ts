import assert from 'node:assert/strict';
import test from 'node:test';
import { matchesPoolFilter } from './poolQuestionFilter.ts';

test('the answered pool filter includes wrong answers because wrong is an answered subset', () => {
  assert.equal(matchesPoolFilter('answered', 'answered'), true);
  assert.equal(matchesPoolFilter('wrong', 'answered'), true);
  assert.equal(matchesPoolFilter('unanswered', 'answered'), false);
  assert.equal(matchesPoolFilter('wrong', 'wrong'), true);
});

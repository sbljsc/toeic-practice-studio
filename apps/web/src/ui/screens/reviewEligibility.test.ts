// The backend accepts reviews only on closed, valid, wrong questions.
// Run with:  node --test apps/web/src/ui/screens/reviewEligibility.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewEligibility } from './reviewEligibility.ts';

test('wrong question on a valid submitted attempt is reviewable', () => {
  const result = reviewEligibility({ result: 'wrong', integrity: 'valid', status: 'submitted' });
  assert.equal(result.allowed, true);
  assert.equal(result.reason, null);
});

test('unanswered is NOT reviewable (regression: form was offered and rejected)', () => {
  const result = reviewEligibility({ result: 'unanswered', integrity: 'valid', status: 'submitted' });
  assert.equal(result.allowed, false);
  assert.match(result.reason ?? '', /没有作答/);
});

test('an interrupted attempt is NOT reviewable', () => {
  for (const status of ['submitted', 'expired']) {
    const result = reviewEligibility({ result: 'wrong', integrity: 'interrupted', status });
    assert.equal(result.allowed, false, `${status}/interrupted must be blocked`);
    assert.match(result.reason ?? '', /中断/);
  }
});

test('a correct question offers no review form', () => {
  const result = reviewEligibility({ result: 'correct', integrity: 'valid', status: 'submitted' });
  assert.equal(result.allowed, false);
  assert.equal(result.reason, null, 'correct answers need no explanatory note');
});

test('an attempt that is not closed cannot be reviewed', () => {
  for (const status of ['ready', 'running', 'paused']) {
    const result = reviewEligibility({ result: 'wrong', integrity: 'valid', status });
    assert.equal(result.allowed, false, `${status} must be blocked`);
  }
});

test('a missing integrity field does not fabricate a block', () => {
  // Older payloads may omit integrity; a wrong question stays reviewable.
  const result = reviewEligibility({ result: 'wrong', integrity: undefined, status: 'submitted' });
  assert.equal(result.allowed, true);
});

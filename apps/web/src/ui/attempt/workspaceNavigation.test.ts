import assert from 'node:assert/strict';
import test from 'node:test';
import type { Attempt } from '../../domain/types.ts';
import { activityTarget, nextEligibleIndex, questionEligible } from './workspaceNavigation.ts';

function attempt(): Attempt {
  return { mode: 'exam', status: 'running', timing: { phase: 'listening', is_paused: false,
    phase_question_ids: ['l1', 'l2'] }, questions: [
    { id: 'l1', part: 1, section: 'listening' }, { id: 'r1', part: 5, section: 'reading' },
    { id: 'l2', part: 2, section: 'listening' }, { id: 'r2', part: 6, section: 'reading' },
  ] } as Attempt;
}
test('auto-next skips phase-ineligible questions and stops at the final eligible question', () => {
  const value = attempt();
  assert.equal(nextEligibleIndex(value, 0), 2);
  assert.equal(nextEligibleIndex(value, 2), null);
  assert.equal(nextEligibleIndex(value, 1), null);
  value.timing.phase = 'reading'; value.timing.phase_question_ids = ['r1', 'r2'];
  assert.equal(nextEligibleIndex(value, 1), 3);
  assert.equal(nextEligibleIndex(value, 0), null);
});
test('paused, ready, closed and explicitly excluded questions cannot auto-next or accrue activity', () => {
  const value = attempt();
  for (const status of ['ready', 'paused', 'submitted', 'expired'] as const) {
    value.status = status;
    assert.equal(nextEligibleIndex(value, 0), null);
    assert.equal(activityTarget(value, 0, true, true, true), null);
  }
  value.status = 'running'; value.timing.is_paused = true;
  assert.equal(questionEligible(value, value.questions[0]), false);
  value.timing.is_paused = false; value.timing.phase_question_ids = ['l2'];
  assert.equal(questionEligible(value, value.questions[0]), false);
});
test('statistics, hidden tabs and former owners send null without changing the attempt timer', () => {
  const value = attempt(), baseline = structuredClone(value);
  assert.equal(activityTarget(value, 0, true, true, true), 'l1');
  for (const args of [[false, true, true], [true, false, true], [true, true, false]]) {
    assert.equal(activityTarget(value, 0, ...args as [boolean, boolean, boolean]), null);
  }
  assert.equal(activityTarget(value, 99, true, true, true), null);
  assert.deepEqual(value, baseline);
});

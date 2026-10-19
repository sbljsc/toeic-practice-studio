import assert from 'node:assert/strict';
import test from 'node:test';
import type { Attempt, AttemptReport } from '../../domain/types.ts';
import { reviewFocusIndex, reviewWorkspace } from './reviewWorkspace.ts';

const report = { attempt: { id: 'closed', status: 'expired', integrity: 'interrupted' }, groups: [],
  questions: [{ id: 'exact-one', number: 99, selected_option_id: 'B' },
    { id: 'exact-two', number: 99, selected_option_id: null }] } as unknown as AttemptReport;
test('closed workspace retains snapshot flags and report selections without acquiring ownership', () => {
  const snapshot = { id: 'closed', answers: { 'exact-one': { flagged: true, visited: true, revision: 8 } }, audio_queue: [] } as unknown as Attempt;
  const value = reviewWorkspace(report, snapshot);
  assert.equal(value.status, 'expired'); assert.equal(value.owner_tab_id, null);
  assert.equal(value.timing.phase, 'finished'); assert.equal(value.timing.can_pause, false);
  assert.equal(value.answers['exact-one'].option_id, 'B'); assert.equal(value.answers['exact-one'].flagged, true);
  assert.equal(value.answers['exact-two'].option_id, null);
  assert.equal(reviewWorkspace(report, { ...snapshot, id: 'other' }).answers['exact-one'].flagged, false);
});
test('review deep links resolve exact ids rather than duplicate printed numbers', () => {
  assert.equal(reviewFocusIndex(report, 'exact-two'), 1);
  assert.equal(reviewFocusIndex(report, 'missing'), 0);
  assert.equal(reviewFocusIndex(report), 0);
});

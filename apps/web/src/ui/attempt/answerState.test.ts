import test from 'node:test';
import assert from 'node:assert/strict';
import { acknowledgeChoice } from './answerState.ts';

test('acknowledging A preserves the newer B choice and pending bookmark', () => {
  const latest = { option_id: 'B' as const, flagged: true, visited: true, revision: 0, dirty: true };
  const sent = { option_id: 'A' as const, flagged: false, visited: true, revision: 0 };
  assert.deepEqual(acknowledgeChoice(latest, sent, 1, true), { ...latest, revision: 1 });
  assert.deepEqual(acknowledgeChoice(latest, latest, 2, false), { ...latest, revision: 2, dirty: false });
});

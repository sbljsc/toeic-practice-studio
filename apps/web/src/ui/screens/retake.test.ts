import test from 'node:test';
import assert from 'node:assert/strict';
import type { AttemptReport } from '../../domain/types.ts';
import { retakeSelection } from './retake.ts';
function report(scope: string, count: number, mode = 'practice'): AttemptReport {
  const fullParts = [6,25,39,30,30,16,54].flatMap((size, i) => Array(size).fill(i + 1));
  return { attempt: { id: 'a', scope, mode, exam_ids: ['test-01'], parts: scope === 'full' ? [1,2,3,4,5,6,7] : [5],
    timer_config: { kind: 'countdown', duration_seconds: 900 } },
    questions: Array.from({ length: count }, (_, i) => ({ id: `q${i}`, exam_id: 'test-01', part: scope === 'full' ? fullParts[i] : 5 })),
    groups: [{ id: 'g101' }, { id: 'g105' }] } as AttemptReport;
}
test('full exam retake preserves the server listening then reading schedule', () => {
  const next = retakeSelection(report('full', 200, 'exam'), null);
  assert.equal(next.scope, 'full'); assert.equal(next.mode, 'exam'); assert.equal(next.groupIds, undefined);
});
test('a filtered Part preserves exactly its actual group set', () => {
  const next = retakeSelection(report('part', 2), null);
  assert.equal(next.scope, 'custom'); assert.deepEqual(next.groupIds, ['g101', 'g105']);
});
test('a complete Part preserves its playback mode and timer', () => {
  const next = retakeSelection(report('part', 30, 'exam'), null);
  assert.equal(next.scope, 'part'); assert.deepEqual(next.parts, [5]); assert.equal(next.timerMinutes, 15);
});
test('custom groups stay custom and a short budget is not rounded to zero', () => {
  const source = report('custom', 2); source.attempt.timer_config!.duration_seconds = 30;
  const next = retakeSelection(source, null);
  assert.equal(next.scope, 'custom'); assert.equal(next.timerMinutes, .5);
  assert.deepEqual(next.groupIds, ['g101', 'g105']);
});

test('a filtered full practice retakes its actual groups even if one entire Part survived', () => {
  const source = report('full', 6);
  source.attempt.parts = [1];
  const next = retakeSelection(source, null);
  assert.equal(next.scope, 'custom');
  assert.deepEqual(next.groupIds, ['g101', 'g105']);
  assert.equal(next.mode, 'practice');
});

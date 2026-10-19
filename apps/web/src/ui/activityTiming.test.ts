import assert from 'node:assert/strict';
import test from 'node:test';
import type { ActivitySummary } from '../domain/types.ts';
import { elapsedText, timingPoints, timingSegments } from './activityTiming.ts';

const summary: ActivitySummary = { coverage: 'partial', total_elapsed_ms: 10000, tracked_ms: 4000,
  unattributed_ms: 6000, questions: [
    { question_id: 'a', number: 41, part: 3, dwell_ms: 0, first_answer_ms: null },
    { question_id: 'b', number: 99, part: 7, dwell_ms: null, first_answer_ms: null },
    { question_id: 'c', number: 101, part: 7, dwell_ms: 4000, first_answer_ms: 2000 },
  ], parts: [{ part: 3, dwell_ms: 0 }, { part: 7, dwell_ms: 4000 }] };
test('missing dwell is a chart gap while recorded zero remains a real point', () => {
  const points = timingPoints(summary, 'question');
  assert.equal(points[0].dwell, 0); assert.equal(points[1].dwell, null);
  assert.deepEqual(timingSegments(points), ['40,170', '780,30']);
  assert.equal(points[2].label, '第 3 题 · Part 7');
  assert.equal(points[2].first, 2000);
});
test('historical unavailable data never becomes inferred timings and Part uses server aggregates', () => {
  assert.deepEqual(timingPoints(undefined, 'question'), []);
  assert.deepEqual(timingPoints({ ...summary, coverage: 'unavailable' }, 'question'), []);
  assert.deepEqual(timingPoints(summary, 'part').map((point) => point.dwell), [0, 4000]);
  assert.equal(elapsedText(null), '未记录'); assert.equal(elapsedText(0), '0.0 秒');
});
test('invalid negative and non-finite values are gaps', () => {
  const value = structuredClone(summary); value.questions[0].dwell_ms = -1; value.questions[2].dwell_ms = NaN;
  assert.deepEqual(timingSegments(timingPoints(value, 'question')), []);
});

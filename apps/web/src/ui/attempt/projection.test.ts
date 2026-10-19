// Regression coverage for strict-exam audio projection, queue boundaries and
// stall detection. These are the defects found in integration review:
//   (2) non-zero Part starts / cross-test queues mis-projected
//   (4) clip end never advanced, so a Part bled into the next Part
//   (3) every healthy exam falsely reported a stall after 5s
// Run with:  node --test apps/web/src/ui/attempt/projection.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  STALL_THRESHOLD_MS,
  absoluteSourceTime,
  buildQueuePlan,
  evaluateStall,
  needsBoundaryAdvance,
  projectQueueElapsed,
  resolveQueuePosition,
} from './projection.ts';

// Real cue geometry from .data/library/audio-cues.json (test-01): Part 2 starts
// at 272.78s, so absolute-elapsed arithmetic is wrong for every later segment.
const QUEUE = [
  { id: 'p1', url: '/api/assets/audio-test-01', start_seconds: 0, end_seconds: 272.78 },
  { id: 'p2', url: '/api/assets/audio-test-01', start_seconds: 272.78, end_seconds: 851.32 },
  { id: 'p3', url: '/api/assets/audio-test-01', start_seconds: 851.32, end_seconds: 1100 },
];

test('queue plan totals cumulative selected durations, not source length', () => {
  const plan = buildQueuePlan(QUEUE);
  assert.equal(plan.segments.length, 3);
  assert.equal(plan.segments[0].durationSeconds, 272.78);
  assert.equal(plan.segments[0].queueOffsetSeconds, 0);
  assert.equal(plan.segments[1].queueOffsetSeconds, 272.78);
  assert.equal(plan.segments[2].queueOffsetSeconds, 851.32);
  assert.equal(Math.round(plan.totalSeconds), 1100);
  // A 1100s queue must never claim the 2961s source duration.
  assert.ok(plan.totalSeconds < 1200);
});

test('elapsed inside Part 2 resolves to Part 2 with correct offset (regression: was clamped to 0)', () => {
  const plan = buildQueuePlan(QUEUE);
  const resolved = resolveQueuePosition(plan, 300);
  assert.ok(resolved);
  assert.equal(resolved.plan.segment.id, 'p2');
  assert.equal(Math.round(resolved.offsetSeconds), 27);
  // Source time must add the Part 2 source start, not queue offset.
  assert.equal(Math.round(absoluteSourceTime(plan, 300)!), 300);
});

test('boundary values land on the following segment (half-open intervals)', () => {
  const plan = buildQueuePlan(QUEUE);
  const atEnd = resolveQueuePosition(plan, 272.78);
  assert.ok(atEnd);
  assert.equal(atEnd.plan.segment.id, 'p2');
  assert.equal(Math.round(atEnd.offsetSeconds), 0);
  const atEnd2 = resolveQueuePosition(plan, 851.32);
  assert.ok(atEnd2);
  assert.equal(atEnd2.plan.segment.id, 'p3');
});

test('cross-test queues project independently of each source timeline', () => {
  const crossQueue = [
    { id: 'a-p2', url: '/api/assets/audio-test-01', start_seconds: 272.78, end_seconds: 851.32 },
    { id: 'b-p1', url: '/api/assets/audio-test-02', start_seconds: 0, end_seconds: 267.2 },
  ];
  const plan = buildQueuePlan(crossQueue);
  assert.equal(plan.segments[1].sourceStart, 0);
  // Each segment keeps its own source offset: test-01 Part 2 adds 272.78s,
  // test-02 Part 1 is 0-based in its own file. No shared source timeline.
  const first = resolveQueuePosition(plan, 300);
  assert.ok(first);
  assert.equal(first.plan.segment.id, 'a-p2');
  assert.equal(Math.round(absoluteSourceTime(plan, 300)!), 573);

  // Past test-01's Part 2 (578.54s) the queue rolls into test-02 and the source
  // time resets to that file's own timeline instead of continuing test-01.
  const second = resolveQueuePosition(plan, 600);
  assert.equal(second.plan.segment.id, 'b-p1');
  assert.equal(Math.round(absoluteSourceTime(plan, 600)!), 21);
});

test('projection uses monotonic drift, not wall-clock', () => {
  // Server said 10s at perf=1000; 5s later we are at 15s.
  assert.equal(projectQueueElapsed(10_000, 1000, 6000), 15);
  // A stale anchor never moves backwards.
  assert.equal(projectQueueElapsed(10_000, 6000, 1000), 10);
});

test('clip end advances before the native file ends (regression: Part bled into next Part)', () => {
  assert.equal(needsBoundaryAdvance({ positionSeconds: 272.7, segmentDurationSeconds: 272.78 }), true);
  assert.equal(needsBoundaryAdvance({ positionSeconds: 272.0, segmentDurationSeconds: 272.78 }), false);
  assert.equal(needsBoundaryAdvance({ positionSeconds: 10, segmentDurationSeconds: 0 }), false);
});

test('healthy playback never reports a stall (regression: false interrupt at 5s)', () => {
  // Progress every second: position advanced, so never stalled regardless of wall time.
  for (let elapsed = 0; elapsed < 30_000; elapsed += 1000) {
    const decision = evaluateStall({
      running: true,
      waiting: false,
      currentTimeMs: elapsed,
      lastProgressTimeMs: elapsed,
      lastProgressPosition: elapsed - 1000,
      nowMs: elapsed + 1000,
      alreadyReported: false,
    });
    assert.equal(decision.stalled, false);
    assert.equal(decision.shouldReport, false);
  }
});

test('a genuine stall reports exactly once after the threshold', () => {
  const base = {
    running: true,
    waiting: false,
    currentTimeMs: 5000,
    lastProgressPosition: 5000,
    nowMs: 5000,
  };
  const frozen = { ...base, lastProgressTimeMs: 5000 };
  const atThreshold = evaluateStall({ ...frozen, nowMs: 5000 + STALL_THRESHOLD_MS });
  assert.equal(atThreshold.stalled, true);
  assert.equal(atThreshold.shouldReport, true);
  const repeated = evaluateStall({ ...frozen, nowMs: 5000 + STALL_THRESHOLD_MS * 2, alreadyReported: true });
  assert.equal(repeated.stalled, true);
  assert.equal(repeated.shouldReport, false, 'must not report the same stall twice');
});

test('prolonged buffering with no progress is a stall, while paused states are not', () => {
  const stalled = {
    running: true,
    currentTimeMs: 1000,
    lastProgressPosition: 1000,
    lastProgressTimeMs: 1000,
    nowMs: 1000 + STALL_THRESHOLD_MS * 2,
    alreadyReported: false,
  };
  assert.equal(evaluateStall({ ...stalled, waiting: true }).stalled, true);
  assert.equal(evaluateStall({ ...stalled, running: false }).stalled, false);
});

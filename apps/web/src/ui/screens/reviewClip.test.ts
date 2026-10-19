// Regression for the review replay bug: selecting a cue segment started the
// shared MP3 at 0 (playing the introduction) instead of at the segment start.
// Run with:  node --test apps/web/src/ui/screens/reviewClip.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clampRate,
  offsetFor,
  reachedClipEnd,
  segmentDuration,
  sourceTimeFor,
} from './reviewClip.ts';

// Real TEST 01 Part 2 cue geometry from the backend's audio_queue.
const part2q7 = { start_seconds: 331.76, end_seconds: 351.76 };
const part2q8 = { start_seconds: 351.76, end_seconds: 371.76 };

test('P0: a segment starts at its own cue offset, never at file 0', () => {
  assert.equal(sourceTimeFor(part2q7, 0), 331.76);
  assert.notEqual(sourceTimeFor(part2q7, 0), 0);
});

test('offset round-trips through the cue boundary', () => {
  assert.equal(offsetFor(part2q7, 331.76), 0);
  assert.equal(offsetFor(part2q7, 341.76), 10);
  assert.equal(offsetFor(part2q7, 351.76), 20);
  assert.equal(sourceTimeFor(part2q7, 10), 341.76);
});

test('later segments use their own timeline (cross-cue is not cumulative)', () => {
  assert.equal(sourceTimeFor(part2q8, 0), 351.76);
  assert.equal(offsetFor(part2q8, 351.76), 0);
});

test('a position from a different segment cannot leak in', () => {
  // offsetFor clamps rather than reporting a negative or oversized value.
  assert.equal(offsetFor(part2q8, 331.76), 0, 'earlier source time clamps to clip start');
  assert.equal(offsetFor(part2q7, 999), 20, 'later source time clamps to clip end');
});

test('clip end preserves the complete ending instead of cutting the last quarter second', () => {
  assert.equal(reachedClipEnd(part2q7, 351.7), false);
  assert.equal(reachedClipEnd(part2q7, 351.76), true);
  assert.equal(reachedClipEnd(part2q7, 351.0), false);
  assert.equal(reachedClipEnd(part2q7, 300), false);
});

test('zero-length or missing segments never report an end', () => {
  assert.equal(reachedClipEnd({ start_seconds: 10, end_seconds: 10 }, 10), false);
  assert.equal(reachedClipEnd(null, 5), false);
  assert.equal(segmentDuration(null), 0);
});

test('rate is clamped to a sane review range', () => {
  assert.equal(clampRate(1), 1);
  assert.equal(clampRate(0.1), 0.5);
  assert.equal(clampRate(9), 2);
});

// Regression coverage for the paused countdown drifting between 5s syncs, and
// for negative drift on the first render after a reload.
// Run with:  node --test apps/web/src/domain/clockProjection.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { projectClock, formatClockMs } from './clockProjection.ts';

const snapshot = { perfAtSync: 10_000, remainingMs: 600_000, elapsedMs: 0 };

test('a live countdown decreases with monotonic drift', () => {
  const result = projectClock(
    { kind: 'countdown', isPaused: false, frozen: false },
    snapshot,
    10_000 + 5_000,
  );
  assert.equal(result.remainingMs, 595_000);
  assert.equal(result.display, '09:55');
});

test('P0: a paused countdown does NOT drift between syncs', () => {
  const atSync = projectClock({ kind: 'countdown', isPaused: true, frozen: true }, snapshot, 10_000);
  const fourSecondsLater = projectClock(
    { kind: 'countdown', isPaused: true, frozen: true },
    snapshot,
    10_000 + 4_000,
  );
  assert.equal(atSync.remainingMs, 600_000);
  assert.equal(fourSecondsLater.remainingMs, 600_000, 'paused must freeze at the server value');
  assert.equal(fourSecondsLater.display, atSync.display);
});

test('P0: a paused countup does not advance', () => {
  const a = projectClock({ kind: 'countup', isPaused: true, frozen: true }, { perfAtSync: 0, remainingMs: null, elapsedMs: 120_000 }, 9_000);
  assert.equal(a.elapsedMs, 120_000);
  assert.equal(a.display, '02:00');
});

test('ready/closed/frozen attempts never drift', () => {
  const result = projectClock(
    { kind: 'countdown', isPaused: false, frozen: true },
    snapshot,
    10_000 + 60_000,
  );
  assert.equal(result.remainingMs, 600_000);
});

test('negative drift on the first render never inflates the countdown', () => {
  // `now` predating the sync sample must clamp to 0 drift, not add time.
  const result = projectClock(
    { kind: 'countdown', isPaused: false, frozen: false },
    snapshot,
    9_000,
  );
  assert.equal(result.remainingMs, 600_000, 'must not show more time than the server reported');
});

test('an expired countdown clamps at zero and reports expired', () => {
  const result = projectClock(
    { kind: 'countdown', isPaused: false, frozen: false },
    { perfAtSync: 0, remainingMs: 3_000, elapsedMs: 0 },
    10_000,
  );
  assert.equal(result.remainingMs, 0);
  assert.equal(result.expired, true);
  assert.equal(result.display, '00:00');
});

test('timers format with hours only when needed', () => {
  assert.equal(formatClockMs(65_000), '01:05');
  assert.equal(formatClockMs(3_725_000), '1:02:05');
  assert.equal(formatClockMs(-5), '00:00');
});

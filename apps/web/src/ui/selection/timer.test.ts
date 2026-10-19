// Regression coverage for the timer contradiction: a full/reading/listening
// mock must show one forced countdown, and a stale stored "none" must never be
// sent for a timed exam scope.
// Run with:  node --test apps/web/src/ui/selection/timer.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveTimerKind, isTimerAllowed, timerRule, READING_EXAM_MINUTES, timerMinutesAfterEdit, timerMinutesAfterScopeChange, validTimerMinutes } from './timer.ts';
import * as timers from './timer.ts';

test('default countdown follows Listening 45, Reading 75 and full 120 minutes', () => {
  const scopes = ['listening', 'reading', 'full'] as const;
  assert.deepEqual(scopes.map((scope) => timers.defaultTimerMinutes?.(scope)), [45, 75, 120]);
});

test('scope changes restore that scope budget, falling back to scope defaults', () => {
  assert.equal(timerMinutesAfterScopeChange('reading', 'listening', 62), 45);
  assert.equal(timerMinutesAfterScopeChange('listening', 'reading', 38), 75);
  assert.equal(timerMinutesAfterScopeChange('reading', 'full', 62), 120);
  assert.equal(timerMinutesAfterScopeChange('reading', 'reading', 62), 62);
  assert.equal(timerMinutesAfterScopeChange('reading', 'part', 18), 45);
  assert.equal(timerMinutesAfterScopeChange('part', 'custom', 18), 45);
  assert.equal(timerMinutesAfterScopeChange('custom', 'part', 20, { part: 17 }), 17);
  assert.equal(timerMinutesAfterScopeChange('part', 'reading', 20, { reading: 63 }), 63);
});

test('timer edits persist independently by scope and reject invalid minute values', () => {
  const initial = {};
  const afterReading = timerMinutesAfterEdit('reading', 63, initial);
  const afterPart = timerMinutesAfterEdit('part', 22, afterReading);
  assert.deepEqual(afterPart, { reading: 63, part: 22 });
  assert.equal(timerMinutesAfterScopeChange('part', 'reading', 22, afterPart), 63);
  assert.equal(timerMinutesAfterScopeChange('reading', 'part', 63, afterPart), 22);
  assert.equal(validTimerMinutes(0), undefined);
  assert.equal(validTimerMinutes(301), undefined);
  assert.equal(validTimerMinutes(Number.NaN), undefined);
  assert.equal(timerMinutesAfterEdit('part', 0, afterPart), afterPart);
});

test('old shared presets migrate once while deliberate custom or newly saved minutes survive', () => {
  assert.equal(timers.restoreTimerMinutes?.('full', 75, undefined), 120);
  assert.equal(timers.restoreTimerMinutes?.('reading', 45, undefined), 75);
  assert.equal(timers.restoreTimerMinutes?.('listening', 75, undefined), 45);
  assert.equal(timers.restoreTimerMinutes?.('full', 62, undefined), 62);
  assert.equal(timers.restoreTimerMinutes?.('part', 75, undefined), 75);
  assert.equal(timers.restoreTimerMinutes?.('full', 75, timers.TIMER_DEFAULTS_VERSION), 75);
  assert.equal(timers.restoreTimerMinutes?.('reading', undefined, undefined), 75);
});

test('full mock forces a countdown and disallows untimed', () => {
  const rule = timerRule('exam', 'full');
  assert.equal(rule.forced, 'countdown');
  assert.equal(isTimerAllowed('exam', 'full', 'none'), false);
  assert.equal(isTimerAllowed('exam', 'full', 'countup'), false);
  assert.equal(isTimerAllowed('exam', 'full', 'countdown'), true);
});

test('reading mock is a timed section fixed at 75 minutes', () => {
  const rule = timerRule('exam', 'reading');
  assert.equal(rule.forced, 'countdown');
  assert.equal(rule.forcedMinutes, READING_EXAM_MINUTES);
  assert.equal(isTimerAllowed('exam', 'reading', 'none'), false);
});

test('listening mock is timed and cannot be untimed', () => {
  const rule = timerRule('exam', 'listening');
  assert.equal(rule.forced, 'countdown');
  assert.equal(isTimerAllowed('exam', 'listening', 'none'), false);
  assert.equal(isTimerAllowed('exam', 'listening', 'countup'), false);
});

test('part and custom mocks may be untimed', () => {
  for (const scope of ['part', 'custom'] as const) {
    assert.equal(timerRule('exam', scope).forced, null);
    assert.equal(isTimerAllowed('exam', scope, 'none'), true);
    assert.equal(isTimerAllowed('exam', scope, 'countdown'), true);
  }
});

test('practice always allows every timer', () => {
  for (const scope of ['full', 'listening', 'reading', 'part', 'custom'] as const) {
    for (const kind of ['countdown', 'countup', 'none'] as const) {
      assert.equal(isTimerAllowed('practice', scope, kind), true, `practice ${scope}/${kind}`);
    }
  }
});

test('P0: a stale stored "none" resolves to countdown for a timed exam', () => {
  // The learner's last practice selection was untimed; switching to a reading
  // mock must send countdown, not the stale "none".
  assert.equal(effectiveTimerKind('exam', 'reading', 'none'), 'countdown');
  assert.equal(effectiveTimerKind('exam', 'full', 'none'), 'countdown');
  assert.equal(effectiveTimerKind('exam', 'listening', 'countup'), 'countdown');
});

test('a valid practice timer is preserved', () => {
  assert.equal(effectiveTimerKind('practice', 'reading', 'none'), 'none');
  assert.equal(effectiveTimerKind('practice', 'part', 'countup'), 'countup');
  assert.equal(effectiveTimerKind('practice', 'custom', 'countdown'), 'countdown');
});

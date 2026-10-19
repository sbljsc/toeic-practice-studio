// Regression coverage for the preflight/header UX gaps found in real browser QA:
// "00:00" shown before start, no visible duration, technical "test-01" source,
// and a duplicated "练习 · 练习" context.
// Run with:  node --test apps/web/src/ui/attempt/headerMeta.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  headerContext,
  headerTimerText,
  plannedDurationText,
  prettyExamId,
  prettyExamIds,
} from './headerMeta.ts';

test('header reads 未开始 before the attempt starts (regression: showed 00:00)', () => {
  assert.equal(headerTimerText({ status: 'ready', kind: 'countdown', display: '00:00' }), '未开始');
  assert.equal(headerContext({ scope: 'reading', mode: 'exam', phase: 'reading', status: 'ready' }), '未开始');
});

test('header shows the real clock once running', () => {
  assert.equal(headerTimerText({ status: 'running', kind: 'countdown', display: '12:34' }), '12:34');
  assert.equal(headerTimerText({ status: 'paused', kind: 'countdown', display: '12:34' }), '12:34');
});

test('duplicated 练习 · 练习 collapses (regression: header showed it twice)', () => {
  const practice = headerContext({ scope: 'part', mode: 'practice', phase: 'practice', status: 'running' });
  assert.equal(practice, 'Part 专项');
  assert.ok(!practice.includes('练习 · 练习'));

  const readingPractice = headerContext({ scope: 'reading', mode: 'practice', phase: 'practice', status: 'running' });
  assert.equal(readingPractice, '仅阅读');
});

test('practice with an explicit section keeps the section visible', () => {
  const value = headerContext({ scope: 'listening', mode: 'practice', phase: 'listening', status: 'running' });
  assert.ok(value.includes('听力'));
  assert.ok(!value.includes('练习 · 练习'));
});

test('exam header shows scope, mode and phase', () => {
  const value = headerContext({ scope: 'full', mode: 'exam', phase: 'listening', status: 'running' });
  assert.ok(value.includes('完整模拟'));
  assert.ok(value.includes('模拟'));
  assert.ok(value.includes('听力'));
});

test('test-01 renders as TEST 01 (regression: technical id shown to learner)', () => {
  assert.equal(prettyExamId('test-01'), 'TEST 01');
  assert.equal(prettyExamId('test-10'), 'TEST 10');
  assert.equal(prettyExamIds({ exam_ids: ['test-01', 'test-02'] }), 'TEST 01、TEST 02');
  assert.equal(prettyExamIds({ exam_ids: ['pool'] }), '随机题库');
  // Unknown ids are passed through rather than mangled.
  assert.equal(prettyExamId('custom-pack'), 'custom-pack');
  assert.equal(prettyExamIds({ exam_ids: [] }), '—');
});

test('preflight duration shows the chosen budget before start, not 00:00', () => {
  const text = plannedDurationText({
    kind: 'countdown',
    remainingMs: null,
    phase: 'reading',
    ready: true,
    plannedSeconds: 60,
  });
  assert.equal(text, '1 分钟（开始后计时）');
});

test('preflight duration falls back honestly when no budget was remembered', () => {
  assert.equal(
    plannedDurationText({ kind: 'countdown', remainingMs: null, phase: 'reading', ready: true, plannedSeconds: null }),
    '开始后计时',
  );
});

test('once running the duration reflects the server remaining time', () => {
  assert.equal(plannedDurationText({ kind: 'countdown', remainingMs: 60_000, phase: 'reading' }), '1 分钟');
  assert.equal(plannedDurationText({ kind: 'countdown', remainingMs: 45_000, phase: 'reading' }), '45 秒');
  assert.equal(plannedDurationText({ kind: 'countdown', remainingMs: 4_500_000, phase: 'reading' }), '1 小时 15 分');
});

test('non-countdown modes keep their plain labels', () => {
  assert.equal(plannedDurationText({ kind: 'none', remainingMs: null, phase: 'practice' }), '不计时');
  assert.equal(plannedDurationText({ kind: 'countup', remainingMs: null, phase: 'practice' }), '正计时');
});

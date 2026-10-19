// Full/listening exams ignore the requested timer payload; the preflight must
// derive the real length from the attempt's own audio queue.
// Run with:  node --test apps/web/src/ui/attempt/examDuration.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { examDuration, formatDurationParts, totalQueueSeconds, READING_EXAM_SECONDS } from './examDuration.ts';
import type { AudioQueueItem } from '../../domain/types.ts';

// Real TEST 01 cue geometry: 4 verified Part cues summing to 49:21.685.
const FULL_QUEUE: AudioQueueItem[] = [
  { id: 'p1', asset_id: 'audio-test-01', url: '/api/assets/audio-test-01', start_seconds: 0, end_seconds: 272.78, part: 1, exam_id: 'test-01', question_ids: [] },
  { id: 'p2', asset_id: 'audio-test-01', url: '/api/assets/audio-test-01', start_seconds: 272.78, end_seconds: 851.32, part: 2, exam_id: 'test-01', question_ids: [] },
  { id: 'p3', asset_id: 'audio-test-01', url: '/api/assets/audio-test-01', start_seconds: 851.32, end_seconds: 1958.26, part: 3, exam_id: 'test-01', question_ids: [] },
  { id: 'p4', asset_id: 'audio-test-01', url: '/api/assets/audio-test-01', start_seconds: 1958.26, end_seconds: 2961.685, part: 4, exam_id: 'test-01', question_ids: [] },
];

test('queue total matches the real 49:21.685 track length', () => {
  assert.equal(formatDurationParts(totalQueueSeconds(FULL_QUEUE)), '49:22');
});

test('P0: full exam shows real listening + 75:00 reading, never the 45min payload', () => {
  const result = examDuration({
    scope: 'full',
    mode: 'exam',
    audioQueue: FULL_QUEUE,
    plannedSeconds: 2700, // the 45 minutes that was being shown
  });
  assert.match(result.text, /听力 49:22/);
  assert.match(result.text, /阅读 1:15:00/);
  assert.match(result.text, /合计 2:04:22/);
  assert.ok(!result.text.includes('45 分钟'), 'must not echo the ignored payload');
});

test('a persisted attempt budget takes precedence over stale local preflight hints and queue length', () => {
  const retake = examDuration({ scope: 'custom', mode: 'practice', audioQueue: FULL_QUEUE,
    timerConfig: { kind: 'countdown', duration_seconds: 60 }, plannedSeconds: 2700 });
  assert.equal(retake.text, '1 分钟（开始后计时）');

  const full = examDuration({ scope: 'full', mode: 'exam', audioQueue: FULL_QUEUE,
    isPoolAttempt: true, timerConfig: { kind: 'countdown', duration_seconds: 7200 }, plannedSeconds: 2700 });
  assert.equal(full.text, '听力 45:00 + 阅读 1:15:00（合计 2:00:00）');

  const historicalLongFull = examDuration({ scope: 'full', mode: 'exam', audioQueue: FULL_QUEUE,
    isPoolAttempt: true, timerConfig: { kind: 'countdown', duration_seconds: 7440 }, plannedSeconds: 7200 });
  assert.equal(historicalLongFull.text, '听力 49:00 + 阅读 1:15:00（合计 2:04:00）');
});

test('persisted listening budget is shown instead of the shorter audio payload', () => {
  const result = examDuration({ scope: 'listening', mode: 'exam', audioQueue: FULL_QUEUE,
    isPoolAttempt: true, timerConfig: { kind: 'countdown', duration_seconds: 2700 }, plannedSeconds: null });
  assert.equal(result.text, '听力 45:00（开始后计时）');
});

test('reading mock retains its contract duration and practice timer kinds are honest', () => {
  assert.equal(examDuration({ scope: 'reading', mode: 'exam', audioQueue: [],
    timerConfig: { kind: 'countdown', duration_seconds: 3600 }, plannedSeconds: null }).text,
  '75 分钟（开始后计时）');
  assert.equal(examDuration({ scope: 'part', mode: 'practice', audioQueue: [],
    timerConfig: { kind: 'none' }, plannedSeconds: 900 }).text, '不计时');
  assert.equal(examDuration({ scope: 'part', mode: 'practice', audioQueue: [],
    timerConfig: { kind: 'countup' }, plannedSeconds: 900 }).text, '正计时');
});

test('listening-only exam shows the real audio length', () => {
  const result = examDuration({
    scope: 'listening',
    mode: 'exam',
    audioQueue: FULL_QUEUE,
    plannedSeconds: 2700,
  });
  assert.match(result.text, /听力 49:22/);
  assert.ok(!/阅读/.test(result.text));
});

test('part and custom keep the learner chosen budget', () => {
  for (const scope of ['part', 'custom'] as const) {
    const result = examDuration({ scope, mode: 'exam', audioQueue: FULL_QUEUE, plannedSeconds: 1800 });
    assert.equal(result.text, '30 分钟（开始后计时）', `${scope} must keep the chosen budget`);
  }
});

test('practice keeps the chosen budget regardless of scope', () => {
  const result = examDuration({
    scope: 'full',
    mode: 'practice',
    audioQueue: FULL_QUEUE,
    plannedSeconds: 1800,
  });
  assert.equal(result.text, '30 分钟（开始后计时）');
});

test('falls back honestly when no budget was remembered', () => {
  assert.equal(
    examDuration({ scope: 'part', mode: 'exam', audioQueue: [], plannedSeconds: null }).text,
    '开始后计时',
  );
});

test('legacy scheduled attempts without timer config still use their original audio queue', () => {
  const result = examDuration({ scope: 'full', mode: 'exam', audioQueue: FULL_QUEUE, plannedSeconds: 7200 });
  assert.match(result.text, /听力 49:22/);
  assert.match(result.text, /合计 2:04:22/);
});

test('legacy strict scheduled attempts ignore old requested timer budgets and use frozen audio segments', () => {
  const legacyFull = examDuration({ scope: 'full', mode: 'exam', audioQueue: FULL_QUEUE,
    timerConfig: { kind: 'countdown', duration_seconds: 2700 }, plannedSeconds: null });
  assert.equal(legacyFull.text, '听力 49:22 + 阅读 1:15:00（合计 2:04:22）');

  const legacyListening = examDuration({ scope: 'listening', mode: 'exam', audioQueue: FULL_QUEUE,
    timerConfig: { kind: 'countdown', duration_seconds: 2700 }, plannedSeconds: null });
  assert.equal(legacyListening.text, '听力 49:22（开始后计时）');
});

test('reading exam duration is the fixed 75 minutes', () => {
  assert.equal(formatDurationParts(READING_EXAM_SECONDS), '1:15:00');
  assert.equal(formatDurationParts(0), '00:00');
  assert.equal(formatDurationParts(7841), '2:10:41');
});

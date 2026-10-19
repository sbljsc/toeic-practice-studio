// Regression coverage for the inverted stage lock that disabled every option
// during the listening phase, plus paused/closed/read-only gating.
// Run with:  node --test apps/web/src/ui/attempt/stageLock.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { stageLock, isCurrentPhaseQuestion } from './stageLock.ts';

const base = {
  phaseQuestionIds: [] as string[],
  status: 'running' as const,
  isPaused: false,
  mode: 'exam' as const,
};

test('P0: listening questions ARE editable while the listening phase runs', () => {
  for (const part of [1, 2, 3, 4]) {
    const lock = stageLock({
      ...base,
      phase: 'listening',
      questionPart: part,
      questionId: `q${part}`,
      section: 'listening',
    });
    assert.equal(lock.editable, true, `Part ${part} must be answerable during listening`);
    assert.equal(lock.reason, null);
  }
});

test('reading questions stay locked during the listening phase', () => {
  for (const part of [5, 6, 7]) {
    const lock = stageLock({
      ...base,
      phase: 'listening',
      questionPart: part,
      questionId: `q${part}`,
      section: 'reading',
    });
    assert.equal(lock.editable, false);
    assert.match(lock.reason ?? '', /听力/);
  }
});

test('listening questions lock once the reading phase starts', () => {
  const lock = stageLock({
    ...base,
    phase: 'reading',
    questionPart: 3,
    questionId: 'q33',
    section: 'listening',
  });
  assert.equal(lock.editable, false);
  assert.match(lock.reason ?? '', /锁定/);
});

test('reading questions are editable during the reading phase', () => {
  const lock = stageLock({
    ...base,
    phase: 'reading',
    questionPart: 7,
    questionId: 'q150',
    section: 'reading',
  });
  assert.equal(lock.editable, true);
  assert.equal(lock.reason, null);
});

test('practice keeps its selected scope editable while running (both sections)', () => {
  for (const section of ['listening', 'reading'] as const) {
    const lock = stageLock({
      ...base,
      mode: 'practice',
      phase: 'practice',
      questionPart: section === 'listening' ? 2 : 6,
      questionId: `p-${section}`,
      section,
    });
    assert.equal(lock.editable, true, `practice ${section} must stay editable`);
  }
});

test('paused disables answering in both phases and both modes', () => {
  for (const mode of ['exam', 'practice'] as const) {
    for (const phase of ['listening', 'reading', 'practice'] as const) {
      const lock = stageLock({
        ...base,
        mode,
        phase,
        isPaused: true,
        questionPart: phase === 'reading' ? 6 : 3,
        questionId: 'q1',
        section: phase === 'reading' ? 'reading' : 'listening',
      });
      assert.equal(lock.editable, false, `${mode}/${phase} paused must be locked`);
      assert.match(lock.reason ?? '', /暂停/);
    }
  }
});

test('ready, submitted and expired attempts are never editable', () => {
  for (const status of ['ready', 'submitted', 'expired'] as const) {
    const lock = stageLock({
      ...base,
      status,
      phase: 'reading',
      questionPart: 5,
      questionId: 'q101',
      section: 'reading',
    });
    assert.equal(lock.editable, false, `${status} must be locked`);
  }
});

test('finished phase is read-only', () => {
  const lock = stageLock({
    ...base,
    phase: 'finished',
    questionPart: 5,
    questionId: 'q101',
    section: 'reading',
  });
  assert.equal(lock.editable, false);
});

test('phase_question_ids identifies current-phase membership', () => {
  assert.equal(isCurrentPhaseQuestion({ phaseQuestionIds: ['a', 'b'], questionId: 'b' }), true);
  assert.equal(isCurrentPhaseQuestion({ phaseQuestionIds: ['a', 'b'], questionId: 'c' }), false);
  // An empty list means the server did not scope the phase; do not lock out.
  assert.equal(isCurrentPhaseQuestion({ phaseQuestionIds: [], questionId: 'anything' }), true);
});

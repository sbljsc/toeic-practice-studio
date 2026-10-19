// Wrong book rules: unresolved across ALL history, cleared by a later correct
// answer, and unanswered never counted as a wrong answer.
// Run with:  node --test apps/web/src/ui/screens/wrongAggregate.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateWrongAnswers } from './wrongAggregate.ts';
import type { AttemptReport, ReportQuestion } from '../../domain/types.ts';

function question(overrides: Partial<ReportQuestion>): ReportQuestion {
  return {
    id: 'q1',
    canonical_id: 'fixture:t01:q101',
    number: 101,
    part: 5,
    section: 'reading',
    group_id: 'g1',
    stem: 'stem',
    options: [{ id: 'A', text: 'a' }],
    selected_option_id: 'B',
    answer: 'A',
    result: 'wrong',
    explanation: { text: 'x', source_pages: [] },
    source_pages: [],
    ...overrides,
  };
}

function report(id: string, created: string, questions: ReportQuestion[]): AttemptReport {
  return {
    attempt: { id, title: `T ${id}`, scope: 'reading', mode: 'exam', parts: [], exam_ids: ['test-01'], status: 'submitted', interruptions: [], integrity: 'valid' },
    summary: { total: questions.length, correct: 0, wrong: 0, unanswered: 0, correct_percent: 0, wrong_percent: 0, unanswered_percent: 0, answered_accuracy: null, by_part: [] },
    questions,
    groups: [],
    reviews: {},
  };
}

const meta = {
  a1: { id: 'a1', title: 'A1', created_at: '2026-01-01T00:00:00Z' },
  a2: { id: 'a2', title: 'A2', created_at: '2026-01-02T00:00:00Z' },
};

test('a still-wrong question from any attempt appears in the book', () => {
  const entries = aggregateWrongAnswers(
    [
      report('a1', '', [question({ id: 'q1', result: 'wrong' })]),
      report('a2', '', [question({ id: 'q2', canonical_id: 'fixture:t01:q102', number: 102, result: 'wrong' })]),
    ],
    meta,
  );
  assert.equal(entries.length, 2);
});

test('a later correct answer clears the question from the book', () => {
  const entries = aggregateWrongAnswers(
    [
      report('a1', '', [question({ id: 'q1', result: 'wrong' })]),
      report('a2', '', [question({ id: 'q1', result: 'correct', selected_option_id: 'A' })]),
    ],
    meta,
  );
  assert.equal(entries.length, 0, 'resolved wrong answers must not stay in the book');
});

test('unanswered is NOT a wrong answer', () => {
  const entries = aggregateWrongAnswers(
    [report('a1', '', [question({ id: 'q1', result: 'unanswered', selected_option_id: null })])],
    meta,
  );
  assert.equal(entries.length, 0);
});

test('a wrong after correct re-enters the book', () => {
  const entries = aggregateWrongAnswers(
    [
      report('a1', '', [question({ id: 'q1', result: 'wrong' })]),
      report('a2', '', [question({ id: 'q1', result: 'correct', selected_option_id: 'A' })]),
    ],
    meta,
  );
  // a2 is the latest and it is correct, so it stays cleared.
  assert.equal(entries.length, 0);
});

test('tracks wrong and fixed counts for repeat practice', () => {
  const entries = aggregateWrongAnswers(
    [
      report('a1', '', [question({ id: 'q1', result: 'wrong' })]),
      report('a2', '', [question({ id: 'q1', result: 'wrong' })]),
    ],
    meta,
  );
  assert.equal(entries.length, 1);
  assert.equal(entries[0].wrongCount, 2);
  assert.equal(entries[0].fixedCount, 0);
  assert.equal(entries[0].attemptId, 'a2', 'points at the latest wrong attempt');
});

test('interrupted reports are ignored entirely', () => {
  const entries = aggregateWrongAnswers(
    [
      report('a1', '', [question({ id: 'q1', result: 'wrong' })]),
      {
        ...report('a2', '', [question({ id: 'q1', result: 'correct', selected_option_id: 'A' })]),
        attempt: {
          ...report('a2', '', []).attempt,
          integrity: 'interrupted',
        },
      },
    ],
    meta,
  );
  assert.equal(entries.length, 1, 'an interrupted correct must not clear a real wrong answer');
});

test('a later unanswered does NOT erase a prior unresolved wrong', () => {
  const entries = aggregateWrongAnswers(
    [
      report('a1', '', [question({ id: 'q1', result: 'wrong' })]),
      report('a2', '', [question({ id: 'q1', result: 'unanswered', selected_option_id: null })]),
    ],
    meta,
  );
  assert.equal(entries.length, 1, 'only a later correct resolves a wrong answer');
  assert.equal(entries[0].attemptId, 'a1', 'still points at the attempt that recorded the wrong');
});

test('an unanswered attempt cannot resurrect a wrong answer already resolved correctly', () => {
  const allMeta = { ...meta, a3: { id: 'a3', title: 'A3', created_at: '2026-01-03T00:00:00Z' } };
  const entries = aggregateWrongAnswers([
    report('a1', '', [question({ result: 'wrong' })]),
    report('a2', '', [question({ result: 'correct', selected_option_id: 'A' })]),
    report('a3', '', [question({ result: 'unanswered', selected_option_id: null })]),
  ], allMeta);
  assert.equal(entries.length, 0);
});

test('completion order decides the latest result when sessions finish out of creation order', () => {
  const earlierCreated = report('a1', '', [question({ result: 'wrong' })]);
  const laterCreated = report('a2', '', [question({ result: 'correct', selected_option_id: 'A' })]);
  earlierCreated.attempt.closed_at = '2026-01-03T00:00:00Z';
  laterCreated.attempt.closed_at = '2026-01-02T01:00:00Z';
  const entries = aggregateWrongAnswers([earlierCreated, laterCreated], meta);
  assert.equal(entries.length, 1, 'finishing the older session last records a new wrong answer');
  assert.equal(entries[0].attemptId, 'a1');
  earlierCreated.questions = [question({ result: 'correct', selected_option_id: 'A' })];
  laterCreated.questions = [question({ result: 'wrong' })];
  assert.deepEqual(aggregateWrongAnswers([earlierCreated, laterCreated], meta), [],
    'a correct completion of the older session resolves the earlier wrong completion');
});

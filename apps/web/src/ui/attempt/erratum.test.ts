// Erratum notes stay answer-neutral and do not expose source numbering/pages.
// Run with:  node --test apps/web/src/ui/attempt/erratum.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { erratumNote } from './erratum.ts';
import type { ReportQuestion } from '../../domain/types.ts';

function question(overrides: Partial<ReportQuestion>): ReportQuestion {
  return {
    id: 't05-q024',
    canonical_id: 'fixture:t05:q024',
    number: 24,
    part: 2,
    section: 'listening',
    group_id: 't05-p2-q024',
    stem: 'Mark your answer on your answer sheet.',
    options: [
      { id: 'A', text: "I'll call to make a reservation." },
      { id: 'B', text: "She's leaving town on Tuesday." },
      { id: 'C', text: 'For three o’clock this afternoon.' },
    ],
    selected_option_id: 'B',
    answer: 'B',
    result: 'correct',
    explanation: { text: '原文解析', source_pages: [200] },
    source_pages: [98],
    ...overrides,
  };
}

test('renders a neutral numbering correction without source numbering or pages', () => {
  const note = erratumNote(
    question({
      source_erratum: {
        kind: 'answer-book-cyclic-content-numbering',
        printed_question_number: 26,
        actual_audio_question_number: 24,
        evidence: 'Original listening PDF p434-435',
      },
    }),
  );
  assert.ok(note);
  assert.equal(note.printedNumber, null);
  assert.match(note.text, /按本轮题目顺序/);
  assert.doesNotMatch(note.text, /第\s*\d+\s*题|印刷|原书/);
  assert.deepEqual(note.sourcePages, []);
});

test('does not expose any supplied source question number', () => {
  const note = erratumNote(
    question({
      source_erratum: { kind: 'answer-book-cyclic-content-numbering' },
      source_review_question_number: 24,
    }),
  );
  assert.ok(note);
  assert.equal(note.printedNumber, null);
  assert.doesNotMatch(note.text, /第\s*\d+\s*题/);
});

test('never leaks an answer or option text into the note', () => {
  const note = erratumNote(
    question({
      source_erratum: {
        kind: 'answer-book-cyclic-content-numbering',
        printed_question_number: 26,
        // The dataset evidence mentions "B/A/A"; it must not reach the UI.
        evidence: 'summary p425 B/A/A retained.',
        summary: 'summary p425 B/A/A retained.',
      },
    }),
  );
  assert.ok(note);
  for (const option of ['reservation', 'Tuesday', 'afternoon']) {
    assert.ok(!note.text.includes(option), `note must not include option text: ${option}`);
  }
  assert.ok(!/\bB\/A\/A\b/.test(note.text), 'note must not include answer keys');
});

test('returns null when a question has no erratum', () => {
  assert.equal(erratumNote(question({})), null);
});

test('bold correction keeps generic wording and does not expose source pages', () => {
  const note = erratumNote(
    question({
      number: 76,
      source_pages: [106],
      source_erratum: {
        kind: 'answer-book-bold-answer-typo',
        retained_answer: 'B',
        misprinted_bold: 'C',
        source_pages: [465],
        evidence: 'listening p464: "any time tomorrow or even this evening"; summary p425 B.',
      },
    }),
  );
  assert.ok(note);
  assert.equal(note.kind, 'bold');
  assert.match(note.text, /题目资料含排版校订/);
  assert.ok(!/音频实际题号/.test(note.text));
  assert.ok(!/印刷为第/.test(note.text));
  assert.equal(note.printedNumber, null);
  assert.deepEqual(note.sourcePages, []);
});

test('bold note never reveals the retained or misprinted letter', () => {
  for (const [retained, misprinted] of [
    ['B', 'D'],
    ['B', 'C'],
  ]) {
    const note = erratumNote(
      question({
        source_erratum: {
          kind: 'answer-book-bold-answer-typo',
          retained_answer: retained,
          misprinted_bold: misprinted,
        },
      }),
    );
    assert.ok(note);
    for (const letter of [retained, misprinted]) {
      assert.ok(
        !note.text.includes(`选项 ${letter}`),
        'must not name an option letter as the answer',
      );
    }
  }
});

test('numbering errata do not reveal source numbers in the current UI', () => {
  const note = erratumNote(
    question({
      source_erratum: {
        kind: 'answer-book-cyclic-content-numbering',
        printed_question_number: 26,
        actual_audio_question_number: 24,
      },
    }),
  );
  assert.ok(note);
  assert.equal(note.kind, 'numbering');
  assert.doesNotMatch(note.text, /第\s*\d+\s*题|音频实际题号/);
});

test('unknown erratum kinds are suppressed rather than guessed', () => {
  assert.equal(erratumNote(question({ source_erratum: { kind: 'something-new' } })), null);
});

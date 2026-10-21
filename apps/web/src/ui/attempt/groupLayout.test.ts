import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Attempt, AttemptGroup, AttemptQuestion } from '../../domain/types';
import {
  groupAtIndex,
  groupOfQuestion,
  groupQuestions,
  nextGroupIndex,
  prevGroupIndex,
  visibleGroups,
} from './groupLayout.ts';

function question(id: string, groupId: string, part = 7): AttemptQuestion {
  return { id, group_id: groupId, part, section: part <= 4 ? 'listening' : 'reading',
    number: 0, canonical_id: `bank:${id}`, exam_id: 'pool', stem: `Stem ${id}`,
    options: ['A', 'B', 'C', 'D'].map((id) => ({ id, text: `Text ${id}` })),
    source_pages: [] };
}

function group(id: string, questionIds: string[], part = 7): AttemptGroup {
  return { id, part, section: part <= 4 ? 'listening' : 'reading', exam_id: 'pool',
    question_ids: questionIds, materials: [], source_pages: [] };
}

/**
 * Two groups of three and two questions. The second group is a listening
 * group so the layout is exercised across sections.
 */
function fixture(): Attempt {
  const questions = [
    question('q1', 'g1'), question('q2', 'g1'), question('q3', 'g1'),
    question('q4', 'g2', 3), question('q5', 'g2', 3),
  ];
  return {
    id: 'a', questions,
    groups: [group('g1', ['q1', 'q2', 'q3']), group('g2', ['q4', 'q5'], 3)],
  } as unknown as Attempt;
}

test('a question is located inside the group that owns it', () => {
  const attempt = fixture();
  const placement = groupOfQuestion(attempt, 'q2');
  assert.ok(placement);
  assert.equal(placement.group.id, 'g1');
  assert.equal(placement.index, 1);
  assert.equal(placement.indexInGroup, 1);
  assert.deepEqual(placement.questions.map((item) => item.id), ['q1', 'q2', 'q3']);
});

test('an unknown question has no group', () => {
  assert.equal(groupOfQuestion(fixture(), 'missing'), undefined);
});

test('the group at a global index reports the index inside that group', () => {
  const attempt = fixture();
  assert.equal(groupAtIndex(attempt, 0)?.group.id, 'g1');
  assert.equal(groupAtIndex(attempt, 0)?.indexInGroup, 0);
  assert.equal(groupAtIndex(attempt, 2)?.group.id, 'g1');
  assert.equal(groupAtIndex(attempt, 2)?.indexInGroup, 2);
  assert.equal(groupAtIndex(attempt, 3)?.group.id, 'g2');
  assert.equal(groupAtIndex(attempt, 3)?.indexInGroup, 0);
  assert.equal(groupAtIndex(attempt, 4)?.indexInGroup, 1);
  assert.equal(groupAtIndex(attempt, 99), undefined);
});

test('a group keeps the answer order of the attempt, not the stored id order', () => {
  const attempt = fixture();
  const shuffled = group('g1', ['q3', 'q1', 'q2']);
  assert.deepEqual(groupQuestions(attempt, shuffled).map((item) => item.id), ['q1', 'q2', 'q3']);
});

test('every group is listed with its questions and its first global index', () => {
  const views = visibleGroups(fixture());
  assert.equal(views.length, 2);
  assert.deepEqual(views[0].questions.map((item) => item.id), ['q1', 'q2', 'q3']);
  assert.equal(views[0].startIndex, 0);
  assert.deepEqual(views[1].questions.map((item) => item.id), ['q4', 'q5']);
  assert.equal(views[1].startIndex, 3);
});

test('the next group starts after the last question of the current one', () => {
  const attempt = fixture();
  // From the first question of g1 the next group starts at index 3.
  assert.equal(nextGroupIndex(attempt, 0), 3);
  // From inside the same group the next group is still the following one.
  assert.equal(nextGroupIndex(attempt, 2), 3);
  assert.equal(nextGroupIndex(attempt, 3), null);
  assert.equal(nextGroupIndex(attempt, 4), null);
});

test('the previous group stops before the first question of the current one', () => {
  const attempt = fixture();
  assert.equal(prevGroupIndex(attempt, 3), 0);
  assert.equal(prevGroupIndex(attempt, 4), 0);
  assert.equal(prevGroupIndex(attempt, 0), null);
  assert.equal(prevGroupIndex(attempt, 1), null);
});

test('a single-question group reports no group neighbour', () => {
  const attempt = { id: 'a',
    questions: [question('q1', 'g1')],
    groups: [group('g1', ['q1'])],
  } as unknown as Attempt;
  assert.equal(nextGroupIndex(attempt, 0), null);
  assert.equal(prevGroupIndex(attempt, 0), null);
});

test('a group whose question is missing from the list still resolves its group', () => {
  const attempt = { id: 'a',
    questions: [question('q1', 'g1'), question('q3', 'g1')],
    groups: [group('g1', ['q1', 'q2', 'q3'])],
  } as unknown as Attempt;
  const placement = groupOfQuestion(attempt, 'q1');
  assert.ok(placement);
  assert.equal(placement.group.id, 'g1');
  assert.deepEqual(placement.questions.map((item) => item.id), ['q1', 'q3']);
});

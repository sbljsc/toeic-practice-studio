// Answer-card filters are display-only: they must preserve each cell's original
// jump index and must never change the attempt scope.
// Run with:  node --test apps/web/src/ui/attempt/answerCardFilter.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { filterCounts, matchesFilter, visibleEntries, type CardEntry } from './answerCardFilter.ts';

interface Q {
  id: string;
}

function entries(): Array<CardEntry<Q>> {
  return [
    { question: { id: 'q1' }, index: 0, state: { optionId: 'A', flagged: true, visited: true }, isCurrent: false },
    { question: { id: 'q2' }, index: 1, state: { optionId: 'B', flagged: false, visited: true }, isCurrent: true },
    { question: { id: 'q3' }, index: 2, state: { optionId: null, flagged: false, visited: true }, isCurrent: false },
    { question: { id: 'q4' }, index: 3, state: { optionId: null, flagged: false, visited: false }, isCurrent: false },
  ];
}

test('counts partition answered vs unanswered and track flags/current', () => {
  const counts = filterCounts(entries());
  assert.equal(counts.all, 4);
  assert.equal(counts.answered, 2);
  assert.equal(counts.unanswered, 2);
  assert.equal(counts.flagged, 1);
  assert.equal(counts.current, 1);
});

test('filtering preserves the original jump index (P0: jumps must not shift)', () => {
  const visible = visibleEntries(entries(), 'answered');
  assert.deepEqual(visible.map((entry) => entry.index), [0, 1]);
  const flagged = visibleEntries(entries(), 'flagged');
  assert.deepEqual(flagged.map((entry) => entry.index), [0]);
  const unanswered = visibleEntries(entries(), 'unanswered');
  assert.deepEqual(unanswered.map((entry) => entry.index), [2, 3]);
});

test('a filtered-out current question can still be reached via current filter', () => {
  // q2 is current and answered; when filtering to unanswered the current cell
  // disappears, but selecting "current" brings it back with its real index.
  const unanswered = visibleEntries(entries(), 'unanswered');
  assert.ok(!unanswered.some((entry) => entry.isCurrent));
  const current = visibleEntries(entries(), 'current');
  assert.deepEqual(current.map((entry) => entry.index), [1]);
});

test('empty result is possible and reports zero', () => {
  const noneFlagged = entries().map((entry) => ({ ...entry, state: { ...entry.state, flagged: false } }));
  const visible = visibleEntries(noneFlagged, 'flagged');
  assert.equal(visible.length, 0);
  assert.equal(filterCounts(noneFlagged).flagged, 0);
});

test('all filter keeps every cell in original order', () => {
  const visible = visibleEntries(entries(), 'all');
  assert.deepEqual(visible.map((entry) => entry.index), [0, 1, 2, 3]);
});

test('matchesFilter is total and defaults to showing everything', () => {
  const entry = entries()[0];
  assert.equal(matchesFilter(entry, 'all'), true);
  assert.equal(matchesFilter(entry, 'answered'), true);
  assert.equal(matchesFilter(entry, 'unanswered'), false);
});

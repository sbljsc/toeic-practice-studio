// A confirmed word can take its meaning from the open word list instead of
// being typed by hand.
import test from 'node:test';
import assert from 'node:assert/strict';
import { needsSenseFill, referenceFor, senseFromReference } from './wordSenseFill.ts';
import type { Candidate, VocabReference } from '../../domain/types';

function reference(word: string, definition = '发票；付款请求书'): VocabReference {
  return {
    word,
    definition: '發票；付款請求書',
    definition_simplified: definition,
    star: 5,
    category: '採購與物流',
    parts_of_speech: ['noun'],
    examples: [],
    attribution: '署名',
    source_url: 'https://example.invalid/',
    license: 'CC BY 4.0',
  };
}

function candidate(term: string, entry: VocabReference | null): Candidate {
  return { term, context: 'ctx', count: 1, reference: entry };
}

test('a candidate brings its own reference', () => {
  const entry = reference('invoice');
  assert.equal(referenceFor('invoice', [candidate('invoice', entry)], null), entry);
});

test('a hand-typed word uses the separately looked-up reference', () => {
  const entry = reference('schedule', '排程；时间表；安排');
  assert.equal(referenceFor('schedule', [], entry), entry);
});

test('a lookup for another word is never borrowed', () => {
  const entry = reference('schedule');
  assert.equal(referenceFor('invoice', [], entry), null);
});

test('a word the list does not know has no reference', () => {
  assert.equal(referenceFor('zzznotaword', [candidate('zzznotaword', null)], null), null);
  assert.equal(senseFromReference(null), '');
});

test('the fill uses the simplified reading and falls back to the source', () => {
  assert.equal(senseFromReference(reference('invoice')), '发票；付款请求书');
  const traditional = { ...reference('x'), definition_simplified: '' };
  assert.equal(senseFromReference(traditional), '發票；付款請求書');
});

test('the fill is offered only while the sense is still empty', () => {
  const entry = reference('invoice');
  assert.equal(needsSenseFill('', entry), true);
  assert.equal(needsSenseFill('   ', entry), true);
  assert.equal(needsSenseFill('我自己写的', entry), false);
  assert.equal(needsSenseFill('', null), false);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { isPhraseQuery, lookupQuery, orderLookup, referenceCredit } from './vocabLookup.ts';
import type { VocabReference } from '../../domain/types';

function entry(word: string): VocabReference {
  return {
    word,
    definition: '释义',
    definition_simplified: '释义',
    star: 5,
    category: '分类',
    parts_of_speech: ['noun'],
    examples: [],
    attribution: '署名',
    source_url: 'https://example.invalid/',
    license: 'CC BY 4.0',
  };
}

test('the query trims what the learner typed', () => {
  assert.equal(lookupQuery('  invoice  '), 'invoice');
  assert.equal(lookupQuery('   '), '');
  assert.equal(lookupQuery(''), '');
});

test('a phrase is a search, a single word may resolve exactly', () => {
  assert.equal(isPhraseQuery('invoice'), false);
  assert.equal(isPhraseQuery('  invoice '), false);
  assert.equal(isPhraseQuery('a glass of'), true);
  assert.equal(isPhraseQuery(''), false);
});

test('an exact entry is not repeated in the match list', () => {
  const outcome = orderLookup({ exact: entry('invoice'), matches: [entry('invoice'), entry('invoices')] });
  assert.equal(outcome.exact?.word, 'invoice');
  assert.deepEqual(outcome.matches.map((m) => m.word), ['invoices']);
});

test('a search without an exact entry keeps every match', () => {
  const outcome = orderLookup({ exact: null, matches: [entry('schedule'), entry('schedules')] });
  assert.equal(outcome.exact, null);
  assert.equal(outcome.matches.length, 2);
});

test('the credit line appears only for licensed reference material', () => {
  assert.equal(referenceCredit(entry('invoice')), '释义与例句来自 CC BY 4.0 词汇库');
  assert.equal(referenceCredit(null), '');
  assert.equal(referenceCredit({ ...entry('x'), license: '' }), '');
});

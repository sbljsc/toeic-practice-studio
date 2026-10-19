import test from 'node:test';
import assert from 'node:assert/strict';
import { applyTextLayout, type TextLayout } from './textLayout.ts';

test('source-backed layout inserts real Markdown headings and preserves source paragraphs without changing text', () => {
  const source = 'Fitness Club\nAn introductory paragraph that ends on a full source row.\nA separate paragraph starts here and wraps\nonto the next source row.\nBenefits\nAll members can use the pool.';
  const layout: TextLayout = { source, paragraphs: [1, 2, 5], hardBreaks: [], headings: [{ line: 0, level: 3 }, { line: 4, level: 4 }] };
  assert.equal(applyTextLayout(source, [layout]), '### Fitness Club\n\nAn introductory paragraph that ends on a full source row.\n\nA separate paragraph starts here and wraps\nonto the next source row.\n#### Benefits\n\nAll members can use the pool.');
});

test('necessary address breaks are explicit and incidental source trailing spaces are not new hard breaks', () => {
  const source = 'From: A  \nTo: B\nPlease attend the meeting  \nnext Monday.';
  assert.equal(applyTextLayout(source, [{ source, paragraphs: [2], hardBreaks: [0], headings: [] }]),
    'From: A  \nTo: B\n\nPlease attend the meeting\nnext Monday.');
});

test('a verified heading spanning extractor rows is one complete heading and suppresses internal paragraph breaks', () => {
  const source = '▶\n解析\n横线处应填入副词。';
  assert.equal(applyTextLayout(source, [{ source, paragraphs: [0, 1, 2], hardBreaks: [], headings: [{ line: 0, endLine: 1, level: 4 }] }]),
    '#### ▶ 解析\n\n横线处应填入副词。');
});

test('a layout applies only to its exact source, including same-length edits and extra text', () => {
  const layout: TextLayout = { source: 'Title\nBody.', paragraphs: [1], hardBreaks: [], headings: [{ line: 0, level: 3 }] };
  assert.equal(applyTextLayout('Other\nBody.', [layout]), undefined);
  assert.equal(applyTextLayout(layout.source + ' extra', [layout]), undefined);
  assert.equal(applyTextLayout(layout.source.replaceAll('\n', '\r\n'), [layout]), '### Title\n\nBody.');
});

test('Part 6 frozen display labels match the entire original template and remain unchanged after formatting', () => {
  const source = 'An offer\nUse {{qid:q-abc}} ------- and {{qid:q-def}} -------.\nA new paragraph.';
  const layout: TextLayout = { source, paragraphs: [1, 2], hardBreaks: [], headings: [{ line: 0, level: 3 }] };
  const frozen = 'An offer\nUse (31) ------- and (32) -------.\nA new paragraph.';
  assert.equal(applyTextLayout(frozen, [layout]), '### An offer\n\nUse (31) ------- and (32) -------.\n\nA new paragraph.');
  assert.equal(applyTextLayout(frozen + ' mismatch', [layout]), undefined);
  assert.equal(applyTextLayout(frozen.replace('(32)', '(0)'), [layout]), undefined);
});

test('ambiguous templates and inconsistent repeated question labels do not choose an arbitrary layout', () => {
  const source = 'Title\nUse {{qid:q-a}} ------- and {{qid:q-a}} -------.';
  const layout: TextLayout = { source, paragraphs: [1], hardBreaks: [], headings: [{ line: 0, level: 3 }] };
  assert.equal(applyTextLayout('Title\nUse (31) ------- and (32) -------.', [layout]), undefined);
  assert.equal(applyTextLayout(source, [layout, { ...layout, headings: [] }]), undefined);
});

test('invalid or conflicting boundary metadata never partially reformats a source', () => {
  const source = 'Title\nBody.';
  for (const invalid of [
    { paragraphs: [2], hardBreaks: [], headings: [] },
    { paragraphs: [1.2], hardBreaks: [], headings: [] },
    { paragraphs: [], hardBreaks: [-1], headings: [] },
    { paragraphs: [], hardBreaks: [], headings: [{ line: 0, level: 7 }] },
    { paragraphs: [], hardBreaks: [0], headings: [{ line: 0, level: 3 }] },
  ]) assert.equal(applyTextLayout(source, [{ source, ...invalid } as TextLayout]), undefined);
});

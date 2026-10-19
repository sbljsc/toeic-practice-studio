import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithOxc } from 'vite';
import { materialImageUrl, parseMaterialInline, parseMaterialMarkdown, verifiedMaterialTranscript } from './materialMarkdown.ts';
import { materialTranscripts } from './materialTranscripts.ts';

// Exercise the real TSX component without adding a runner/dependency or loading CSS in Node.
const componentUrl = new URL('../ui/MaterialContent.tsx', import.meta.url);
const componentRequire = createRequire(componentUrl);
const source = readFileSync(componentUrl, 'utf8').replace("import './MaterialContent.css';", '');
const code = (await transformWithOxc(source, 'MaterialContent.tsx', {})).code.replace(
  /from (["'])([^"']+)\1/g, (_match, _quote, name) => `from ${JSON.stringify(name.startsWith('.')
    ? new URL(name + '.ts', componentUrl).href : pathToFileURL(componentRequire.resolve(name)).href)}`);
const { MaterialContent } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

test('prose, headings, both list kinds and starting number retain content', () => {
  assert.deepEqual(parseMaterialMarkdown('# Heading\r\n\r\nFrom: A\r\nTo: B\n\n- First\n- Second\n\n3. Third\n4. Fourth'), [
    { kind: 'heading', level: 1, text: 'Heading' }, { kind: 'paragraph', text: 'From: A\nTo: B' },
    { kind: 'list', ordered: false, start: 1, items: ['First', 'Second'] },
    { kind: 'list', ordered: true, start: 3, items: ['Third', 'Fourth'] },
  ]);
});

test('table preserves empty checkmark cells, column alignment, escaped pipes and all totals', () => {
  const blocks = parseMaterialMarkdown('| Quality | Good | Fair | Poor |\n| :--- | :---: | ---: | --- |\n| Taste | √ | | |\n| A\\|B | | | √ |');
  assert.deepEqual(blocks, [{ kind: 'table', header: ['Quality', 'Good', 'Fair', 'Poor'],
    align: ['left', 'center', 'right', 'left'], rows: [['Taste', '√', '', ''], ['A\\|B', '', '', '√']] }]);
  const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'text', text: '| A | B |\n| --- | --- |\n| x\\|y | **$0.00** |' }] }));
  assert.match(html, /<td[^>]*>x\|y<\/td>/);
  assert.match(html, /<strong>\$0.00<\/strong>/);
  assert.match(html, /scope="col"/); assert.match(html, /role="region"/); assert.match(html, /tabindex="0"/);
});

test('malformed or ragged tables remain literal without dropping cells', () => {
  for (const text of ['A | B\n--- | ---\nx | y | EXTRA', 'A | B\n-- | ---\nx | y']) {
    const blocks = parseMaterialMarkdown(text);
    assert.deepEqual(blocks, [{ kind: 'paragraph', text }]);
  }
});

test('emphasis, literal markers, identifiers and dynamic labels survive', () => {
  const text = '**4** *Title* ***Both*** \\*footnote account_name {{qid:q-abc123}} -------- unmatched*';
  const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'text', text }] }));
  assert.match(html, /<strong>4<\/strong>/); assert.match(html, /<em>Title<\/em>/);
  assert.match(html, /<strong><em>Both<\/em><\/strong>/);
  assert.match(html, /\*footnote account_name {{qid:q-abc123}} -------- unmatched\*/);
});

test('raw HTML, Markdown links and embeds never create active elements', () => {
  const payload = '<script>alert(1)</script> <img src=x onerror=alert(1)>\n[click](javascript:alert(1))\n![remote](https://evil.test/a.png)\n<iframe src="https://evil.test"></iframe>';
  const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'text', text: payload }] }));
  assert.doesNotMatch(html, /<(?:script|img|iframe|a)\b/i); assert.match(html, /&lt;script&gt;/);
  assert.match(html, /\[click\]\(javascript:alert\(1\)\)/);
});

test('only local registered asset endpoints load; image OCR is not repeated', () => {
  for (const url of ['https://evil.test/x', '//evil.test/x', 'data:image/svg+xml,x', '/api/assets/../x', '/api/assets/x?redirect=x', '/api/assets/x%2fy', 'javascript:alert(1)']) assert.equal(materialImageUrl(url), undefined);
  const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'image', url: '/api/assets/img-123', alt: '路线图', text: 'REPEATED OCR' }] }));
  assert.match(html, /src="\/api\/assets\/img-123"/); assert.match(html, /alt="路线图"/); assert.doesNotMatch(html, /REPEATED OCR/);
  const fallback = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'image', url: 'https://evil.test/a', text: '<fallback>' }] }));
  assert.doesNotMatch(fallback, /<img|fallback/); assert.match(fallback, /题目图片暂不可用/);
});

test('frozen image snapshots render only source-verified transcripts without duplicate pixels or OCR', () => {
  const id = 'img-083265820a6445614cd8';
  const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [
    { kind: 'image', asset_id: id, url: `/api/assets/${id}`, text: 'unverified replacement OCR' },
  ] }));
  assert.match(html, /<table>/); assert.match(html, /<strong>4<\/strong>/);
  assert.doesNotMatch(html, /<img|unverified replacement OCR/);
  assert.equal(verifiedMaterialTranscript({ asset_id: '__proto__', text: 'x' }), undefined);
  assert.equal(verifiedMaterialTranscript({ asset_id: 'img-1e23073638bcd5ea1aa8', text: 'food OCR' }), undefined);
});

test('frozen Part 6 preserves each actual displayed number and refuses mismatched source templates', () => {
  const [id, entry] = Object.entries(materialTranscripts).find(([, value]) => value.sourceText)!;
  let n = 60;
  const frozen = entry.sourceText!.replace(/\{\{qid:[^}]+\}\}/g, () => `(${++n})`);
  const output = verifiedMaterialTranscript({ asset_id: id, text: frozen })!;
  assert.ok(output); assert.doesNotMatch(output, /\{\{qid:/);
  for (const label of ['(61)', '(62)', '(63)', '(64)']) assert.ok(output.includes(label));
  const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'image', asset_id: id, url: `/api/assets/${id}`, text: frozen }] }));
  assert.doesNotMatch(html, /<img|\{\{qid:/);
  for (const label of ['(61)', '(62)', '(63)', '(64)']) assert.ok(html.includes(label));
  assert.equal(verifiedMaterialTranscript({ asset_id: id, text: frozen + 'UNVERIFIED' }), undefined);
  assert.equal(verifiedMaterialTranscript({ asset_id: id }), undefined);
  assert.equal(verifiedMaterialTranscript({ asset_id: id, text: entry.sourceText }), entry.markdown);
});

test('the complete verified map renders every table with source rows and checkmarks intact', () => {
  assert.equal(Object.keys(materialTranscripts).length, 80);
  for (const [id, value] of Object.entries(materialTranscripts)) {
    const blocks = parseMaterialMarkdown(value.markdown);
    const html = renderToStaticMarkup(createElement(MaterialContent, { materials: [{ kind: 'text', text: value.markdown }] }));
    assert.doesNotMatch(html, /<(?:script|iframe|a|img)\b/i, id);
    assert.equal((html.match(/<td\b/g) ?? []).length, blocks.reduce((sum, block) => sum + (block.kind === 'table' ? block.rows.length * block.header.length : 0), 0), id);
  }
  const food = parseMaterialMarkdown(materialTranscripts['img-a0e025170c8126cc3b74'].markdown)[0];
  assert.equal(food.kind, 'table');
  if (food.kind === 'table') assert.deepEqual(food.rows, [['Taste','√','','',''],['Variety','','','√',''],['Price','√','','','']]);
});

test('multi-line list details stay attached to the relevant original receipt choice', () => {
  const block = parseMaterialMarkdown('- □ Return after **30** days\n  □ by express mail □ by normal mail\n- ■ Forward:\n  Mr. Chow\n  55 Canton Road')[0];
  assert.deepEqual(block, { kind: 'list', ordered: false, start: 1, items: ['□ Return after **30** days\n□ by express mail □ by normal mail', '■ Forward:\nMr. Chow\n55 Canton Road'] });
});

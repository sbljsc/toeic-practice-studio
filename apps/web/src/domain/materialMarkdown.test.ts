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
const { MaterialContent, MarkdownText, MarkdownInline } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

test('soft PDF line wraps reflow without breaking English words, Chinese or compound hyphens', () => {
  assert.deepEqual(parseMaterialMarkdown('We have a 200-\nsquare-foot room with the latest\nexercise equipment.', 'prose'), [
    { kind: 'paragraph', text: 'We have a 200-square-foot room with the latest exercise equipment.' },
  ]);
  assert.deepEqual(parseMaterialMarkdown('照看\n10\n岁以下的孩子。\n请选\n(B)\n。', 'prose'), [
    { kind: 'paragraph', text: '照看10岁以下的孩子。请选(B)。' },
  ]);
});

test('Markdown paragraphs and explicit hard breaks are retained while ordinary newlines soften', () => {
  assert.deepEqual(parseMaterialMarkdown('First line wraps\nhere.\n\nLine one  \nLine two\\\nLine three.', 'prose'), [
    { kind: 'paragraph', text: 'First line wraps here.' },
    { kind: 'paragraph', text: 'Line one\nLine two\nLine three.' },
  ]);
});

test('document structure retains mail fields, address lines, salutations and signatures', () => {
  assert.deepEqual(parseMaterialMarkdown('From: A\nTo: B\nSubject: Visit\nDear Mr. Cooper,\nPlease attend the annual meeting at our head office next week,\nwhere the team will present the schedule.\nBest regards,\nNed Urschel\n55 Canton Road\nDetroit, Michigan 70456'), [
    { kind: 'paragraph', text: 'From: A\nTo: B\nSubject: Visit' },
    { kind: 'paragraph', text: 'Dear Mr. Cooper,' },
    { kind: 'paragraph', text: 'Please attend the annual meeting at our head office next week, where the team will present the schedule.' },
    { kind: 'paragraph', text: 'Best regards,\nNed Urschel\n55 Canton Road\nDetroit, Michigan 70456' },
  ]);
});

test('letterhead with corporate punctuation, a separator, postal address and date stays structured', () => {
  const blocks = parseMaterialMarkdown('G&G INC\n_______________________\nGeneral and Green, Inc.\nOne Security Drive\nNicholasville, Kentucky 40356\nNed R. Urschel, Vice President and\nManaging Director\nOctober 29, 2018\nUnisys Ltd.\n2F, Bay Center Building\nDetroit, Michigan 70456\nAttention: Mr. Stanley Cooper, Vice President\nDear Mr. Cooper,\nThe annual class will take place at our head office next month, and\nwe would like you to attend.');
  assert.deepEqual(blocks.map(b => b.text), [
    'G&G INC', '_______________________',
    'General and Green, Inc.\nOne Security Drive\nNicholasville, Kentucky 40356\nNed R. Urschel, Vice President and Managing Director\nOctober 29, 2018\nUnisys Ltd.\n2F, Bay Center Building\nDetroit, Michigan 70456\nAttention: Mr. Stanley Cooper, Vice President',
    'Dear Mr. Cooper,', 'The annual class will take place at our head office next month, and we would like you to attend.',
  ]);
});

test('legacy document titles and paragraph endings become spaced paragraphs, not PDF-length rows', () => {
  const blocks = parseMaterialMarkdown('Fitness Club\nAre you tired of waiting for exercise equipment in a crowded room? Our\nnew club has everything you need.\nRead what our members have to say:\n“We now enjoy a workout with the trainers who are always ready to help\nwhen we need them!”');
  assert.deepEqual(blocks, [
    { kind: 'paragraph', text: 'Fitness Club' },
    { kind: 'paragraph', text: 'Are you tired of waiting for exercise equipment in a crowded room? Our new club has everything you need.' },
    { kind: 'paragraph', text: 'Read what our members have to say:' },
    { kind: 'paragraph', text: '“We now enjoy a workout with the trainers who are always ready to help when we need them!”' },
  ]);
});

test('chat turns and English/Chinese speaker turns keep their boundaries and reflow each turn', () => {
  const blocks = parseMaterialMarkdown('Amy Wilson [11:05 A.M.]\nMy plane landed, and I am waiting in the baggage claim area for\nmy suitcase.\nJacob Vance [11:08 A.M.]\nI am glad to hear it.\n\nM:\nDo you know why the meeting\nwas postponed?\nW: The manager is away.\n\nM: 你知道为什么会议\n延期了吗？\nW: 经理出差了。');
  assert.deepEqual(blocks.map(b => b.text), [
    'Amy Wilson [11:05 A.M.]\nMy plane landed, and I am waiting in the baggage claim area for my suitcase.',
    'Jacob Vance [11:08 A.M.]\nI am glad to hear it.',
    'M: Do you know why the meeting was postponed?', 'W: The manager is away.',
    'M: 你知道为什么会议延期了吗？', 'W: 经理出差了。',
  ]);
});

test('split option markers and explanation sections remain legible without splitting letters and brackets', () => {
  const blocks = parseMaterialMarkdown('Why was the trip postponed?\n（\nA\n）\nShe had to attend to other\nbusiness.\n（\nB\n）她错过了早班\n飞机。\n▶\n解析\n横线处需要填入形容词，与\nrespectful词性相同。');
  assert.deepEqual(blocks.map(b => b.text), [
    'Why was the trip postponed?', '（A） She had to attend to other business.',
    '（B）她错过了早班飞机。', '▶ 解析', '横线处需要填入形容词，与respectful词性相同。',
  ]);
});

test('bilingual choices separate translation prompts and preserve Chinese numbers after punctuation', () => {
  const blocks = parseMaterialMarkdown('(C) A room with private saunas\n(D) Free swimming lessons for regulars\n以下哪项服务没有在广告中提到？\n(A)\n专业人员指导的个人锻炼\n→他们拥有专业队伍，\n10\n多个专家。');
  assert.deepEqual(blocks.map(b => b.text), [
    '(C) A room with private saunas', '(D) Free swimming lessons for regulars',
    '以下哪项服务没有在广告中提到？', '(A)专业人员指导的个人锻炼', '→他们拥有专业队伍，10多个专家。',
  ]);
});

test('standalone introductions have paragraph spacing, and isolated Chinese quotation marks do not fragment a quote', () => {
  const blocks = parseMaterialMarkdown('Our trainers provide a service designed to meet every member’s individual needs.\nRead what our members have to say:\n“\n他们拥有专业的队伍，\n10\n多个专家帮助会员。我原以为无法锻炼了\n…\n现在每天锻炼！\n”\n来自纽约的会员');
  assert.deepEqual(blocks.map(b => b.text), [
    'Our trainers provide a service designed to meet every member’s individual needs.',
    'Read what our members have to say:', '“他们拥有专业的队伍，10多个专家帮助会员。我原以为无法锻炼了…现在每天锻炼！”', '来自纽约的会员',
  ]);
});

test('short Chinese continuations and supplementary listening examples are not mistaken for headings or swallowed by choices', () => {
  assert.deepEqual(parseMaterialMarkdown('我也想要一些\n东西。'), [{ kind: 'paragraph', text: '我也想要一些东西。' }]);
  assert.deepEqual(parseMaterialMarkdown('（D）一位男士正在指挥另一个人。\n·A man is operating heavy machinery.\n一位男士正在操作笨重的\n机器。\n·Heavy machinery is being used.\n笨重的机器正在被使用。').map(b => b.text), [
    '（D）一位男士正在指挥另一个人。', '·A man is operating heavy machinery.', '一位男士正在操作笨重的机器。',
    '·Heavy machinery is being used.', '笨重的机器正在被使用。',
  ]);
});

test('a source line break around a middle dot in a Chinese name does not create an example paragraph', () => {
  assert.deepEqual(parseMaterialMarkdown('戴维\n·\n韦尔斯今天的演讲做得很好，是吧？'), [
    { kind: 'paragraph', text: '戴维·韦尔斯今天的演讲做得很好，是吧？' },
  ]);
});

test('shared block and inline renderers support Markdown without introducing active content or invalid button descendants', () => {
  const block = renderToStaticMarkup(createElement(MarkdownText, { text: '**First** line\nwraps.\n\nSecond paragraph.', flow: 'prose' }));
  assert.match(block, /<p><strong>First<\/strong> line wraps\.<\/p><p>Second paragraph\.<\/p>/);
  const option = renderToStaticMarkup(createElement('button', null, createElement(MarkdownInline, { text: '**The** company will\nreopen on Monday. <img src=x>' })));
  assert.match(option, /<strong>The<\/strong> company will reopen on Monday\. &lt;img src=x&gt;/);
  assert.doesNotMatch(option, /<(?:p|div|table|img)\b/);
});

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

test('grammar blanks remain literal underscores instead of being consumed as Markdown emphasis', () => {
  const text = 'will ______ send 是“情态动词+______+谓语动词”的结构。\n\nUse ___ or ______ for the blank; ___emphasis___ remains emphasis.';
  const html = renderToStaticMarkup(createElement(MarkdownText, { text, flow: 'prose' }));
  assert.match(html, /will ______ send/);
  assert.match(html, /情态动词\+______\+谓语动词/);
  assert.match(html, /Use ___ or ______ for the blank/);
  assert.match(html, /<strong><em>emphasis<\/em><\/strong>/);
});

test('split source bullet markers become actual lists without swallowing wrapped item text or literal footnote stars', () => {
  const text = '《证券\n*\n交易法案》\n\n讨论以下内容：\n* \n在遇到难以相处的人和难以应对的困境时，\n如何高效地工作\n* \n避免和解决冲突\n* \n达到平衡的积极性\n\n在讨论会结束时，会发给大家总结手册。';
  const blocks = parseMaterialMarkdown(text);
  assert.deepEqual(blocks, [
    { kind: 'paragraph', text: '《证券\\*交易法案》' },
    { kind: 'paragraph', text: '讨论以下内容：' },
    { kind: 'list', ordered: false, start: 1, items: ['在遇到难以相处的人和难以应对的困境时，如何高效地工作', '避免和解决冲突', '达到平衡的积极性'] },
    { kind: 'paragraph', text: '在讨论会结束时，会发给大家总结手册。' },
  ]);
  const html = renderToStaticMarkup(createElement(MarkdownText, { text }));
  assert.match(html, /《证券\*交易法案》/);
  assert.equal((html.match(/<li>/g) ?? []).length, 3);
  assert.doesNotMatch(html, /<em>/);
});

test('an isolated hyphen from a wrapped blank is not a bullet and list continuations stop at choices and explanations', () => {
  assert.deepEqual(parseMaterialMarkdown('It should be proofread ------\n-\nby someone else.\n(A) equally\n(B) thoroughly\n▶\n解析'), [
    { kind: 'paragraph', text: 'It should be proofread ------- by someone else.' },
    { kind: 'paragraph', text: '(A) equally' }, { kind: 'paragraph', text: '(B) thoroughly' },
    { kind: 'paragraph', text: '▶ 解析' },
  ]);
  const blocks = parseMaterialMarkdown('* \nItem\n(A) one\n(B) two\n▶\n解析');
  assert.deepEqual(blocks[0], { kind: 'list', ordered: false, start: 1, items: ['Item'] });
  assert.equal(blocks.filter(block => block.kind === 'paragraph').length, 3);
});

test('ordered source numbering restarts at section boundaries and preserves deliberately nonconsecutive numbers', () => {
  const html = renderToStaticMarkup(createElement(MarkdownText, { text: '1. First item.\nAnswer line.\nResults\n1. Next item.\nAnswer line.' }));
  assert.equal((html.match(/<ol start="1">/g) ?? []).length, 2);
  const nonconsecutive = renderToStaticMarkup(createElement(MarkdownText, { text: '2. Second\n4. Fourth' }));
  assert.match(nonconsecutive, /<li value="4">Fourth<\/li>/);
});

test('loose consecutive ordered items remain one list while a year ending with a period remains prose', () => {
  assert.deepEqual(parseMaterialMarkdown('1. First item.\n\n2. Second item.\n\n3. Third item.'), [
    { kind: 'list', ordered: true, start: 1, items: ['First item.', 'Second item.', 'Third item.'] },
  ]);
  const html = renderToStaticMarkup(createElement(MarkdownText, { text: 'Goals for the year\n2019.  \nAttendance is mandatory.' }));
  assert.doesNotMatch(html, /<ol|<li/);
  assert.match(html, /2019\./);
});

test('split dash bullets are recovered in list context without consuming a wrapped grammar blank', () => {
  assert.deepEqual(parseMaterialMarkdown('- \nfirst item\n- \nsecond item'), [
    { kind: 'list', ordered: false, start: 1, items: ['first item', 'second item'] },
  ]);
  const blocks = parseMaterialMarkdown('优惠如下：\n\n-\n购买五公斤，赠送一公斤。\n\n-\n购买八公斤，赠送两公斤。');
  assert.equal(blocks.filter(block => block.kind === 'list').length, 1);
  assert.deepEqual(parseMaterialMarkdown('proofread ------\n-\nby someone else.', 'prose'), [
    { kind: 'paragraph', text: 'proofread ------- by someone else.' },
  ]);
});

test('split short ordered markers retain source list semantics without turning a standalone year into a list', () => {
  assert.deepEqual(parseMaterialMarkdown('以下任务：\n1. \n识别器械。\n2. \n评估情况。'), [
    { kind: 'paragraph', text: '以下任务：' },
    { kind: 'list', ordered: true, start: 1, items: ['识别器械。', '评估情况。'] },
  ]);
  assert.doesNotMatch(renderToStaticMarkup(createElement(MarkdownText, { text: '2019.\nAttendance is mandatory.' })), /<ol|<li/);
  const numericChoices = renderToStaticMarkup(createElement(MarkdownText, { text: 'How many?\n（\nA\n）\n36.\n（\nB\n）\n50.\n（\nC\n）\n100.' }));
  assert.doesNotMatch(numericChoices, /<ol|<li/);
  assert.match(numericChoices, /36\./);
  assert.match(numericChoices, /50\./);
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
  assert.match(html, /src="\/api\/assets\/img-123"/); assert.match(html, /alt="路线图"/);
  // The picture carries the material; its written description repeats the
  // same content and stays folded away instead of sitting beside the image.
  assert.match(html, /<details/); assert.match(html, /REPEATED OCR/);
  assert.doesNotMatch(html, /<img[^>]*>\s*<p>REPEATED OCR/);
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

import assert from 'node:assert/strict';
import test from 'node:test';
import { textLayouts } from './textLayouts.ts';
import { parseMaterialMarkdown } from './materialMarkdown.ts';

test('the reviewed fitness advertisement has a real title and keeps each testimonial separate from its attribution', () => {
  const layout = textLayouts.find(row => row.source.startsWith('Fantasy Fitness\n'));
  assert.ok(layout, 'The complete source document needs layout metadata even when it contains attribution bullets.');
  const blocks = parseMaterialMarkdown(layout.source);
  assert.deepEqual(blocks[0], { kind: 'heading', level: 3, text: 'Fantasy Fitness' });
  const attributions = blocks.flatMap(block => block.kind === 'list' ? block.items : []);
  assert.deepEqual(attributions, ['Dave from New York', 'Jane from Los Angeles', 'Bob from Texas']);
  assert.equal(blocks.filter(block => block.kind === 'paragraph' && block.text.startsWith('“')).length, 3);
});

test('the actual letterhead keeps postal fields and salutation apart from the letter body', () => {
  const layout = textLayouts.find(row => row.source.startsWith('G&G INC\n'));
  assert.ok(layout);
  const blocks = parseMaterialMarkdown(layout.source);
  const paragraphs = blocks.flatMap(block => block.kind === 'paragraph' ? [block.text] : []);
  assert.ok(paragraphs.some(text => text.includes('One Security Drive\nNicholasville, Kentucky 40356')));
  assert.ok(paragraphs.includes('Dear Mr. Cooper,'));
  assert.ok(paragraphs.some(text => text.startsWith('General & Green will be conducting')));
  assert.ok(paragraphs.some(text => text.startsWith('Also, this is a reminder')));
});

test('separate centered source titles are rendered with their actual heading hierarchy', () => {
  const layout = textLayouts.find(row => row.source.startsWith('THE INSTANT PLAYER’S GUIDE\n'));
  assert.ok(layout);
  const headings = parseMaterialMarkdown(layout.source).filter(block => block.kind === 'heading');
  assert.deepEqual(headings.slice(0, 3), [
    { kind: 'heading', level: 3, text: 'THE INSTANT PLAYER’S GUIDE' },
    { kind: 'heading', level: 4, text: 'INSTANT GAME INFORMATION' },
    { kind: 'heading', level: 4, text: 'Current and Upcoming Games' },
  ]);
});

test('the actual split analysis marker is rendered as a complete fourth-level heading', () => {
  const layout = textLayouts.find(row => row.headings.some(heading => heading.endLine !== undefined));
  assert.ok(layout);
  const blocks = parseMaterialMarkdown(layout.source);
  assert.ok(blocks.some(block => block.kind === 'heading' && block.level === 4 && block.text === '▶ 解析'));
  assert.ok(!blocks.some(block => block.kind === 'heading' && block.text === '▶'));
});

test('a body-sized advertisement headline is still a third-level title rather than merged into prose', () => {
  const layout = textLayouts.find(row => row.source.startsWith('Secondhand Goods for Sale\n'));
  assert.ok(layout);
  assert.deepEqual(parseMaterialMarkdown(layout.source)[0], { kind: 'heading', level: 3, text: 'Secondhand Goods for Sale' });
});

test('the workshop notice reflows body text while its four-person attendance list keeps separate rows', () => {
  const layout = textLayouts.find(row => row.source.startsWith('New Employee Workshop\n'));
  assert.ok(layout);
  const paragraphs = parseMaterialMarkdown(layout.source).flatMap(block => block.kind === 'paragraph' ? [block.text] : []);
  assert.ok(paragraphs.some(text => text.includes('goals for the year 2019.')));
  const rows = paragraphs.flatMap(text => text.split('\n'));
  for (const name of ['John Stack', 'Mary Fisher', 'Terry Dillon', 'Sean Gomez']) assert.ok(rows.includes(name), name);
});

test('the coffee order keeps customer fields distinct and the translated offer stops after its fourth bullet', () => {
  const form = textLayouts.find(row => row.source.startsWith('Caraway Coffee\nis having a special sale'));
  assert.ok(form);
  const fields = parseMaterialMarkdown(form.source).flatMap(block => block.kind === 'paragraph' ? block.text.split('\n') : []);
  for (const prefix of ['Customer Name:', 'Address:', 'Phone Number:', 'Order Number:', 'Order Date:', 'Delivery Date:']) {
    assert.ok(fields.some(text => text.startsWith(prefix)), prefix);
  }
  const translation = textLayouts.find(row => row.source.startsWith('葛缕子咖啡店\n特价销售咖啡豆'));
  assert.ok(translation);
  const translated = parseMaterialMarkdown(translation.source);
  assert.deepEqual(translated[0], { kind: 'heading', level: 3, text: '葛缕子咖啡店' });
  const offer = translated.find(block => block.kind === 'list');
  assert.ok(offer?.kind === 'list');
  assert.equal(offer.items.length, 4);
  assert.ok(offer.items[3].endsWith('6公斤。'));
  assert.ok(translated.some(block => block.kind === 'paragraph' && block.text.startsWith('此优惠适用于')));
});

// The Markdown bank carries the presentation that the old runtime layout
// table used to compute. These tests assert that the bank still separates
// titles from body text, keeps heading levels, keeps list rows apart and
// keeps tables intact.
import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { parseMaterialMarkdown } from './materialMarkdown.ts';

const PARTS = path.resolve(import.meta.dirname, '../../../../content/question-pool/parts');

const partFolders = (): string[] =>
  readdirSync(PARTS, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);

/** Read one group file from whichever part folder holds it. */
function groupFile(name: string): string {
  for (const part of partFolders()) {
    const candidate = path.join(PARTS, part, name);
    if (existsSync(candidate)) return readFileSync(candidate, 'utf8');
  }
  throw new Error(`group file not found: ${name}`);
}

/** The material the API serves for a group, with its headings intact. */
function originalSection(text: string): string {
  const start = text.indexOf('## 原文');
  if (start < 0) return '';
  const rest = text.slice(start + 4);
  const end = rest.indexOf('## 选项');
  const section = end < 0 ? rest : rest.slice(0, end);
  // The listening script and the textbook review block sit before the
  // material; the API serves the material that follows a "Material N" marker.
  const marker = section.search(/^#{2,6}\s+(?:Material|Passage)\s+\d+\s*$/m);
  const material = marker >= 0 ? section.slice(marker) : section;
  return material.replace(/^#{2,6}\s+(?:Material|Passage)\s+\d+\s*$/m, '').trim();
}

test('a real title in the bank stays a heading and not part of the prose', () => {
  const blocks = parseMaterialMarkdown(originalSection(groupFile('g-0fd4a7156a100c32b802.md')), 'document');
  const headings = blocks.filter((block) => block.kind === 'heading');
  assert.ok(headings.length > 0, 'the calendar keeps its title as a heading');
  const first = headings[0] as { level: number; text: string };
  assert.equal(first.level, 3);
  assert.ok(first.text.length > 0);
});

test('the table of a real bank material survives as a table', () => {
  const blocks = parseMaterialMarkdown(originalSection(groupFile('g-0fd4a7156a100c32b802.md')), 'document');
  const tables = blocks.filter((block) => block.kind === 'table');
  assert.ok(tables.length > 0, 'the calendar keeps its weekday table');
  const table = tables[0] as { header: string[]; rows: string[][] };
  assert.ok(table.header.length >= 2);
  assert.ok(table.rows.length > 0);
  for (const row of table.rows) assert.equal(row.length, table.header.length);
});

test('a real fourth-level section keeps its level', () => {
  const blocks = parseMaterialMarkdown(originalSection(groupFile('g-0810a0e6c69557c42bd6.md')), 'document');
  const levels = blocks
    .filter((block) => block.kind === 'heading')
    .map((block) => (block as { level: number }).level);
  assert.ok(levels.includes(4), 'the Part 6 material keeps a fourth-level section');
});

test('a real list keeps its rows apart instead of merging them', () => {
  const blocks = parseMaterialMarkdown(originalSection(groupFile('g-babcc5c34315125d82f2.md')), 'document');
  const lists = blocks.filter((block) => block.kind === 'list');
  assert.ok(lists.length > 0, 'the list stays a list');
  const items = lists.flatMap((block) => (block as { items: string[] }).items);
  assert.ok(items.length > 1, 'its rows stay separate');
  assert.ok(new Set(items).size === items.length, 'no row is repeated');
});

test('the bank never shows a bare marker where a heading belongs', () => {
  for (const name of ['g-0fd4a7156a100c32b802.md', 'g-0810a0e6c69557c42bd6.md']) {
    const blocks = parseMaterialMarkdown(originalSection(groupFile(name)), 'document');
    for (const block of blocks) {
      if (block.kind !== 'heading') continue;
      assert.ok(block.text.trim().length > 0, 'a heading is never empty');
    }
  }
});
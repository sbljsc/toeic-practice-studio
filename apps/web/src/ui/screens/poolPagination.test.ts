import assert from 'node:assert/strict';
import test from 'node:test';
import { pageSlice } from './poolPagination.ts';

test('compact bank pages retain canonical order and never drop the final partial page', () => {
  const items = Array.from({ length: 203 }, (_, index) => `q${index + 1}`);
  const pages = [1, 2, 3].map((page) => pageSlice(items, page));
  assert.deepEqual(pages.map((page) => page.items.length), [100, 100, 3]);
  assert.deepEqual(pages.flatMap((page) => page.items), items);
  assert.equal(pageSlice(items, 9).page, 3);
});
test('filtered lists, empty lists and page size changes clamp the visible page honestly', () => {
  assert.deepEqual(pageSlice([], 10), { page: 1, pages: 1, items: [] });
  assert.deepEqual(pageSlice(['exact-id'], 10).items, ['exact-id']);
  assert.equal(pageSlice([1, 2, 3], -4, 2).page, 1);
  assert.equal(pageSlice([1, 2, 3], NaN, 0).pages, 3);
});

// The badge in the top right says what the update is doing and what can be
// clicked next.
import test from 'node:test';
import assert from 'node:assert/strict';
import { updateBadge } from './updateIndicator.ts';
import type { UpdateStatus } from '../domain/types';

function state(overrides: Partial<UpdateStatus>): UpdateStatus {
  return {
    current_version: '0.4.0',
    latest_version: null,
    update_available: false,
    checked: false,
    portable: true,
    error: null,
    phase: 'idle',
    downloaded_bytes: 0,
    total_bytes: 0,
    ...overrides,
  };
}

test('nothing is shown when there is nothing to say', () => {
  assert.equal(updateBadge(state({ phase: 'idle' })).label, '');
  assert.equal(updateBadge(state({ phase: 'current' })).label, '');
});

test('a new release offers itself', () => {
  const badge = updateBadge(state({ phase: 'available', latest_version: '0.5.0', update_available: true }));
  assert.equal(badge.label, '可更新');
  assert.equal(badge.clickable, true);
});

test('the download shows its progress and cannot be clicked', () => {
  const badge = updateBadge(
    state({ phase: 'downloading', downloaded_bytes: 50, total_bytes: 200 }));
  assert.equal(badge.label, '下载中 25%');
  assert.equal(badge.percent, 25);
  assert.equal(badge.clickable, false);
});

test('a download without a known size still shows that it runs', () => {
  const badge = updateBadge(state({ phase: 'downloading', downloaded_bytes: 10, total_bytes: 0 }));
  assert.equal(badge.label, '下载中…');
  assert.equal(badge.percent, null);
  assert.equal(badge.clickable, false);
});

test('a finished download asks for the restart', () => {
  const badge = updateBadge(state({ phase: 'ready', latest_version: '0.5.0' }));
  assert.equal(badge.label, '待重启');
  assert.equal(badge.clickable, true);
});

test('checking is not clickable', () => {
  const badge = updateBadge(state({ phase: 'checking' }));
  assert.equal(badge.label, '检查更新…');
  assert.equal(badge.clickable, false);
});

test('a failed check can be tried again', () => {
  const badge = updateBadge(state({ phase: 'error' }));
  assert.equal(badge.label, '更新失败');
  assert.equal(badge.clickable, true);
});

test('the progress never goes past the whole file', () => {
  const badge = updateBadge(
    state({ phase: 'downloading', downloaded_bytes: 500, total_bytes: 200 }));
  assert.equal(badge.percent, 100);
});
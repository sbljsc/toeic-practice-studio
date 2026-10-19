import test from 'node:test';
import assert from 'node:assert/strict';
import type { AttemptReport } from '../../domain/types.ts';
import { ReportRequestGate } from './reportState.ts';
const report = (id: string, integrity = 'valid') => ({ attempt: { id, integrity,
  interruptions: integrity === 'interrupted' ? [{ event_id: 'confirmed' }] : [] } }) as AttemptReport;

test('a held clean report cannot replace the newer acknowledged interruption', () => {
  const gate = new ReportRequestGate();
  gate.select('a');
  const old = gate.begin('a'), updated = gate.begin('a');
  assert.equal(gate.accept(updated, report('a', 'interrupted'))?.attempt.integrity, 'interrupted');
  assert.equal(gate.accept(old, report('a')), null);
  const later = gate.begin('a');
  assert.equal(gate.accept(later, report('a'))?.attempt.integrity, 'interrupted');
});
test('navigating attempts and unmounting fence old success and error responses', () => {
  const gate = new ReportRequestGate(); gate.select('a');
  const old = gate.begin('a');
  gate.select('b');
  assert.equal(gate.current(old), false);
  assert.equal(gate.accept(old, report('a')), null);
  const next = gate.begin('b');
  assert.equal(gate.accept(next, report('b'))?.attempt.integrity, 'valid');
  gate.invalidate(); assert.equal(gate.current(next), false);
});

test('an old save callback cannot start another report request after navigation', () => {
  const gate = new ReportRequestGate(), requests: string[] = [];
  const load = (id: string) => {
    const token = gate.begin(id);
    if (token) requests.push(id);
    return token;
  };
  gate.select('a'); load('a');
  const oldSaveCompleted = () => load('a');
  gate.select('b'); const b = load('b');
  oldSaveCompleted();
  assert.deepEqual(requests, ['a', 'b']);
  assert.ok(b && gate.current(b), 'a stale callback must not invalidate the current report request');
});

test('a save completing after unmount cannot start another request', () => {
  const gate = new ReportRequestGate(); gate.select('a');
  gate.begin('a');
  const oldSaveCompleted = () => gate.begin('a');
  gate.invalidate();
  assert.equal(oldSaveCompleted(), null);
});

test('mount effect can reactivate after cleanup without reviving obsolete responses', () => {
  const gate = new ReportRequestGate(); gate.select('a'); gate.activate('a');
  const previous = gate.begin('a');
  gate.invalidate(); gate.activate('a');
  const current = gate.begin('a');
  assert.ok(current && gate.current(current));
  assert.equal(gate.accept(previous, report('a')), null);
  gate.select('b'); gate.activate('a');
  assert.equal(gate.begin('a'), null, 'obsolete lifecycle setup cannot revive the old identity');
});

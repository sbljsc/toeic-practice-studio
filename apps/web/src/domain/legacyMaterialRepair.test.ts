import assert from 'node:assert/strict';
import test from 'node:test';
import { repairLegacyMaterial } from './legacyMaterialRepair.ts';
import { legacyMaterialRepairs } from './legacyMaterialRepairs.ts';

test('the reviewed missing Part 6 marker follows actual stable-ID numbers, including shuffled frozen attempts', () => {
  const repair = legacyMaterialRepairs[0];
  const ids = [...repair.source.matchAll(/\{\{qid:([^}]+)\}\}/g)].map(m => m[1]);
  const numbers = { [repair.questionId]: 90, ...Object.fromEntries(ids.map((id, at) => [id, 89 + at * 2])) };
  const frozen = repair.source.replace(/\{\{qid:([^}]+)\}\}/g, (_, id) => `(${numbers[id]})`);
  const output = repairLegacyMaterial(frozen, numbers);
  assert.equal(output, frozen.replace('(140)', '(90)'));
  assert.match(output, /\(90\) -\n-------/);
  assert.match(frozen, /\(140\)/); // Input snapshot is untouched.
});

test('no guessing from order, missing ID, a different source, or inconsistent other labels', () => {
  const repair = legacyMaterialRepairs[0];
  const ids = [...repair.source.matchAll(/\{\{qid:([^}]+)\}\}/g)].map(m => m[1]);
  const numbers = { [repair.questionId]: 32, ...Object.fromEntries(ids.map((id, at) => [id, 31 + at])) };
  const frozen = repair.source.replace(/\{\{qid:([^}]+)\}\}/g, (_, id) => `(${numbers[id]})`);
  for (const value of [frozen + 'extra', frozen.replace('prizes', 'offers'), frozen.replace('(31)', '(99)')]) {
    assert.equal(repairLegacyMaterial(value, numbers), value);
  }
  assert.equal(repairLegacyMaterial(frozen), frozen);
  assert.equal(repairLegacyMaterial(frozen, { [repair.questionId]: 0 }), frozen);
});

test('a different blank already numbered 140 keeps its number when the missing marker is repaired', () => {
  const repair = legacyMaterialRepairs[0];
  const ids = [...repair.source.matchAll(/\{\{qid:([^}]+)\}\}/g)].map(m => m[1]);
  const numbers = { [repair.questionId]: 141, ...Object.fromEntries(ids.map((id, at) => [id, at === 0 ? 140 : 141 + at])) };
  const substitute = (text: string) => text.replace(/\{\{qid:([^}]+)\}\}/g, (_, id) => `(${numbers[id]})`);
  const frozen = substitute(repair.source);
  const output = repairLegacyMaterial(frozen, numbers);
  assert.equal(output, substitute(repair.repaired));
  assert.match(output, /tickets \(140\)/);
  assert.match(output, /and \(141\) -\n-------/);
});

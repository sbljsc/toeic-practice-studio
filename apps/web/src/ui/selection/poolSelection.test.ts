import assert from 'node:assert/strict';
import test from 'node:test';
import { canAssembleTarget } from './poolSelection.ts';

test('pool target feasibility keeps groups whole and can combine different group sizes', () => {
  assert.equal(canAssembleTarget(7, [3, 4, 6]), true);
  assert.equal(canAssembleTarget(5, [3, 4, 6]), false);
  assert.equal(canAssembleTarget(6, [3, 3, 4]), true);
});

test('pool target feasibility rejects invalid counts and accepts zero for an omitted custom Part', () => {
  assert.equal(canAssembleTarget(0, [3, 4]), true);
  assert.equal(canAssembleTarget(-1, [3, 4]), false);
  assert.equal(canAssembleTarget(3.5, [3, 4]), false);
});

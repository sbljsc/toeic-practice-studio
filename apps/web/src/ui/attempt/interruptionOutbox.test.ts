import test from 'node:test';
import assert from 'node:assert/strict';
import { DurableInterruptionQueue, InterruptionOutbox, type OutboxStorage, type PendingInterruption } from './interruptionOutbox.ts';

class MemoryStorage implements OutboxStorage {
  data = new Map<string, string>();
  get length() { return this.data.size; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
}
const event = (event_id: string, attempt_id = 'a'): PendingInterruption =>
  ({ event_id, attempt_id, reason: '缓冲中断', occurred_at_ms: 1000 });
test('failed interruption delivery survives a new document until explicitly acknowledged', () => {
  const storage = new MemoryStorage(), first = new InterruptionOutbox(storage);
  first.add(event('one'));
  const reloaded = new InterruptionOutbox(storage);
  assert.deepEqual(reloaded.pending('a'), [event('one')]);
  reloaded.remove('one'); assert.deepEqual(first.pending('a'), []);
});
test('two tabs and attempts keep independent events; one ack cannot erase another', () => {
  const storage = new MemoryStorage(), a = new InterruptionOutbox(storage), b = new InterruptionOutbox(storage);
  a.add(event('one')); b.add(event('two')); b.add(event('other', 'b'));
  a.remove('one'); assert.deepEqual(b.pending('a'), [event('two')]);
  assert.deepEqual(a.pending('b'), [event('other', 'b')]);
});

test('a failed workspace event retries after report navigation and a document restart with its original owner', async () => {
  const storage = new MemoryStorage();
  const original = { ...event('late'), owner_tab_id: 'original-tab' };
  const workspace = new DurableInterruptionQueue(new InterruptionOutbox(storage));
  workspace.add(original);
  await workspace.flush(async () => { throw new Error('offline'); }, () => assert.fail('no ack'));
  const report = new DurableInterruptionQueue(new InterruptionOutbox(storage));
  assert.equal(report.pending('a').length, 1);
  const deliveries: PendingInterruption[] = [], acknowledgments: string[] = [];
  await report.flush(async (item) => { deliveries.push(item); return true; }, (item) => acknowledgments.push(item.event_id));
  assert.deepEqual(deliveries, [original]);
  assert.deepEqual(acknowledgments, ['late']);
  assert.equal(report.pending('a').length, 0);
});

test('parallel retries join a single delivery and another failed attempt remains pending', async () => {
  const queue = new DurableInterruptionQueue(null);
  queue.add(event('one')); queue.add(event('two', 'b'));
  let release: (() => void) | undefined, calls = 0;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const deliver = async (item: PendingInterruption) => { calls++; await gate; return item.attempt_id === 'a'; };
  const first = queue.flush(deliver, () => undefined);
  const second = queue.flush(deliver, () => assert.fail('must join existing worker'));
  assert.equal(first, second); assert.equal(calls, 1);
  release!(); await first;
  assert.equal(calls, 2);
  assert.deepEqual(queue.pending(), [event('two', 'b')]);
});

// Regression coverage for concurrent per-question writes: rapid A->B clicks,
// stale acknowledgments deleting newer drafts, submit flush, and the
// reconnect-after-takeover stale-revision path.
// Run with:  node --test apps/web/src/ui/attempt/answerQueue.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { AnswerWriteQueue, summarizeFlush, type AnswerValue, type SendFn } from './answerQueue.ts';

const results = (drains: Map<string, { result: { ok: boolean } }>) =>
  summarizeFlush(
    new Map([...drains].map(([id, drain]) => [id, drain.result as never])),
  );

const value = (option_id: AnswerValue['option_id'], revision = 0): AnswerValue => ({
  option_id,
  flagged: false,
  visited: true,
  revision,
});

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

test('rapid A->B serializes and the newest value is sent last', async () => {
  const queue = new AnswerWriteQueue();
  const sent: Array<{ option: string; mutation: string }> = [];
  const first = deferred<{ ok: true; revision: number }>();

  const send: SendFn = async (_id, v, mutationId) => {
    sent.push({ option: String(v.option_id), mutation: mutationId });
    if (sent.length === 1) return first.promise;
    return { ok: true, revision: 2 };
  };

  queue.enqueue('q1', value('A'), 'mutation-a');
  const draining = queue.drain('q1', send);
  // The learner changes their mind while the first write is still in flight.
  queue.enqueue('q1', value('B'), 'mutation-b');
  first.resolve({ ok: true, revision: 1 });
  await draining;

  assert.deepEqual(sent, [
    { option: 'A', mutation: 'mutation-a' },
    { option: 'B', mutation: 'mutation-b' },
  ]);
});

test('only one write per question is ever in flight', async () => {
  const queue = new AnswerWriteQueue();
  let concurrent = 0;
  let maxConcurrent = 0;
  const send: SendFn = async () => {
    concurrent += 1;
    maxConcurrent = Math.max(maxConcurrent, concurrent);
    await new Promise((r) => setTimeout(r, 5));
    concurrent -= 1;
    return { ok: true, revision: 1 };
  };
  queue.enqueue('q1', value('A'), 'm1');
  queue.enqueue('q1', value('B'), 'm2');
  queue.enqueue('q1', value('C'), 'm3');
  await queue.drain('q1', send);
  assert.equal(maxConcurrent, 1);
});

test('a stale acknowledgment cannot settle state a newer write owns', () => {
  const queue = new AnswerWriteQueue();
  const stale = queue.enqueue('q1', value('A'), 'm1');
  const fresh = queue.enqueue('q1', value('B'), 'm2');
  // Settling the older sequence must be refused while the newer one is pending.
  assert.equal(queue.settle('q1', stale.sequence), false);
  assert.equal(queue.isStale('q1', stale.sequence), true);
  assert.equal(queue.hasPending('q1'), true);
  assert.equal(queue.isStale('q1', fresh.sequence), false);
  assert.equal(queue.settle('q1', fresh.sequence), true);
  assert.equal(queue.hasPending('q1'), false);
});

test('drain reports the sequence it sent so a late enqueue is never settled', async () => {
  const queue = new AnswerWriteQueue();
  const gate = deferred<{ ok: true; revision: number }>();
  const send: SendFn = async () => gate.promise;
  queue.enqueue('q1', value('A'), 'm1');
  const draining = queue.drain('q1', send);
  gate.resolve({ ok: true, revision: 1 });
  const drained = await draining;
  assert.equal(drained.result.ok, true);
  // A write that lands after the drain must be detected as newer.
  queue.enqueue('q1', value('B'), 'm2');
  assert.equal(queue.isStale('q1', drained.sequence), true);
});

test('coalescing keeps only the newest value for a burst', async () => {
  const queue = new AnswerWriteQueue();
  const gate = deferred<{ ok: true; revision: number }>();
  const sent: Array<string> = [];
  const send: SendFn = async (_id, v) => {
    sent.push(String(v.option_id));
    if (sent.length === 1) return gate.promise;
    return { ok: true, revision: 9 };
  };
  queue.enqueue('q1', value('A'), 'm1');
  const draining = queue.drain('q1', send);
  // Five rapid clicks collapse into one follow-up write of the final choice.
  queue.enqueue('q1', value('B'), 'm2');
  queue.enqueue('q1', value('C'), 'm3');
  queue.enqueue('q1', value('D'), 'm4');
  queue.enqueue('q1', value('A'), 'm5');
  gate.resolve({ ok: true, revision: 1 });
  await draining;
  assert.deepEqual(sent, ['A', 'A']);
});

test('submit flush drains every question and blocks on failure', async () => {
  const queue = new AnswerWriteQueue();
  const seen: string[] = [];
  const send: SendFn = async (id) => {
    seen.push(id);
    if (id === 'q2') return { ok: false, kind: 'error', message: 'offline' };
    return { ok: true, revision: 1 };
  };
  queue.enqueue('q1', value('A'), 'm1');
  queue.enqueue('q2', value('B'), 'm2');
  const outcome = results(await queue.drainAll(send));
  assert.deepEqual(seen.sort(), ['q1', 'q2']);
  assert.equal(outcome.ok, false);
  assert.equal(outcome.failed, 1);
});

test('submit flush succeeds only when every question is acknowledged', async () => {
  const queue = new AnswerWriteQueue();
  const send: SendFn = async () => ({ ok: true, revision: 1 });
  queue.enqueue('q1', value('A'), 'm1');
  queue.enqueue('q2', value('B'), 'm2');
  const outcome = results(await queue.drainAll(send));
  assert.deepEqual(outcome, { ok: true, failed: 0, aborted: 0 });
});

test('flush honors an abort (read-only takeover) without writing', async () => {
  const queue = new AnswerWriteQueue();
  let writes = 0;
  const send: SendFn = async () => {
    writes += 1;
    return { ok: true, revision: 1 };
  };
  queue.enqueue('q1', value('A'), 'm1');
  const outcome = results(await queue.drainAll(send, () => true));
  assert.equal(writes, 0, 'a non-owning tab must never send');
  assert.equal(outcome.aborted, 1);
  assert.equal(outcome.ok, false, 'an unacknowledged ownership abort must block submit');
});

test('conflict result is reported as a failure so submit stays blocked', async () => {
  const queue = new AnswerWriteQueue();
  const send: SendFn = async () => ({ ok: false, kind: 'conflict', server: value('C', 4) });
  queue.enqueue('q1', value('A'), 'm1');
  const outcome = results(await queue.drainAll(send));
  assert.equal(outcome.ok, false);
  assert.equal(outcome.failed, 1);
});

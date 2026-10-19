import test from 'node:test';
import assert from 'node:assert/strict';
import { AnswerWriteQueue, summarizeFlush, type AnswerValue, type SendFn, type SendResult } from './answerQueue.ts';

const value = (option: AnswerValue['option_id'], revision = 0): AnswerValue =>
  ({ option_id: option, revision, flagged: false, visited: true });
const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
};

test('a failed mutation stays available for an explicit retry with the same id', async () => {
  const queue = new AnswerWriteQueue();
  const ids: string[] = [];
  let online = false;
  const send: SendFn = async (_q, _v, id) => {
    ids.push(id);
    return online ? { ok: true, revision: 1 } : { ok: false, kind: 'error', message: 'offline' };
  };
  queue.enqueue('q', value('B'), 'durable-id');
  assert.equal((await queue.drain('q', send)).result.ok, false);
  assert.deepEqual(queue.pendingQuestionIds(), ['q']);
  online = true;
  assert.equal((await queue.drain('q', send)).result.ok, true);
  assert.deepEqual(ids, ['durable-id', 'durable-id']);
});

test('submit flush waits for an already running send, then sees its acknowledgment', async () => {
  const queue = new AnswerWriteQueue();
  const gate = deferred<SendResult>();
  queue.enqueue('q', value('A'), 'm');
  const saving = queue.drain('q', async () => gate.promise);
  let settled = false;
  const flushing = queue.drainAll(async () => { throw new Error('must join original send'); })
    .then((result) => { settled = true; return result; });
  try {
    await new Promise((done) => setTimeout(done, 5));
    assert.equal(settled, false, 'a pending answer cannot be reported as a successful flush');
  } finally {
    gate.resolve({ ok: true, revision: 1 });
  }
  await saving;
  const result = await flushing;
  assert.equal(summarizeFlush(new Map([...result].map(([id, r]) => [id, r.result]))).ok, true);
});

test('rapid A then B uses the revision acknowledged by A for the dependent B write', async () => {
  const queue = new AnswerWriteQueue();
  const gate = deferred<SendResult>();
  const revisions: number[] = [];
  const send: SendFn = async (_q, v) => {
    revisions.push(v.revision);
    if (revisions.length === 1) return gate.promise;
    return v.revision === 1 ? { ok: true, revision: 2 }
      : { ok: false, kind: 'conflict', server: value('A', 1) };
  };
  queue.enqueue('q', value('A'), 'a');
  const saving = queue.drain('q', send);
  queue.enqueue('q', value('B'), 'b');
  gate.resolve({ ok: true, revision: 1 });
  assert.equal((await saving).result.ok, true);
  assert.deepEqual(revisions, [0, 1]);
});

test('acknowledgment loss is retried idempotently before a newer desired choice', async () => {
  const queue = new AnswerWriteQueue();
  const gate = deferred<SendResult>();
  const sent: Array<[string, number]> = [];
  let serverRevision = 0;
  const send: SendFn = async (_q, v, id) => {
    sent.push([id, v.revision]);
    if (sent.length === 1) { serverRevision = 1; return gate.promise; }
    if (id === 'a') return { ok: true, revision: serverRevision };
    if (v.revision !== serverRevision) return { ok: false, kind: 'conflict', server: value('A', serverRevision) };
    return { ok: true, revision: ++serverRevision };
  };
  queue.enqueue('q', value('A'), 'a');
  const saving = queue.drain('q', send);
  queue.enqueue('q', value('B'), 'b');
  gate.resolve({ ok: false, kind: 'error', message: 'response lost after commit' });
  assert.equal((await saving).result.ok, false);
  assert.equal((await queue.drain('q', send)).result.ok, true);
  assert.deepEqual(sent, [['a', 0], ['a', 0], ['b', 1]]);
});

test('an ownership abort blocks submit instead of silently counting as saved', () => {
  assert.deepEqual(summarizeFlush(new Map([['q', { ok: false, kind: 'aborted' }]])),
    { ok: false, failed: 0, aborted: 1 });
});

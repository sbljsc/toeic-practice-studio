import assert from 'node:assert/strict';
import test from 'node:test';
import type { ActivityEvent } from '../../domain/types.ts';
import { ActivityChannel } from './activityChannel.ts';

const settle = () => new Promise<void>((resolve) => setImmediate(resolve));
test('activity has one in-flight PUT and coalesces queued transitions to the latest target', async () => {
  const events: ActivityEvent[] = [];
  let release!: () => void;
  const channel = new ActivityChannel(async (event) => {
    events.push(event);
    if (events.length === 1) await new Promise<void>((resolve) => { release = resolve; });
  });
  channel.select('owner', 'q1');
  channel.select('owner', 'q2'); channel.pulse(); channel.select('owner', null);
  assert.equal(events.length, 1);
  release(); await settle();
  assert.deepEqual(events, [
    { session_id: 'owner', sequence: 1, question_id: 'q1' },
    { session_id: 'owner', sequence: 2, question_id: null },
  ]);
});

test('takeover while a PUT is held discards the queued old session and starts the new sequence', async () => {
  const events: ActivityEvent[] = [];
  let release!: () => void;
  const channel = new ActivityChannel(async (event) => {
    events.push(event);
    if (events.length === 1) await new Promise<void>((resolve) => { release = resolve; });
  });
  channel.select('old', 'q1'); channel.select('old', 'q2');
  channel.select(null, null); channel.select('new', 'q3');
  release(); await settle();
  assert.deepEqual(events.map((event) => [event.session_id, event.sequence, event.question_id]),
    [['old', 1, 'q1'], ['new', 1, 'q3']]);
});

test('ownership loss cancels pending PUTs and a resumed session never reuses sequence numbers', async () => {
  const events: ActivityEvent[] = [];
  let release!: () => void;
  const channel = new ActivityChannel(async (event) => {
    events.push(event);
    if (events.length === 1) await new Promise<void>((resolve) => { release = resolve; });
  });
  channel.select('owner', 'q1'); channel.select('owner', 'q2'); channel.select(null, null);
  release(); await settle(); assert.equal(events.length, 1);
  channel.select('owner', 'q3'); await settle();
  assert.equal(events[1].sequence, 2); assert.equal(events[1].question_id, 'q3');
});

test('failed delivery is not retried; the next heartbeat represents the current target', async () => {
  const events: ActivityEvent[] = [];
  const channel = new ActivityChannel(async (event) => { events.push(event); throw Error('offline'); });
  channel.select('owner', 'q1'); await settle();
  assert.equal(events.length, 1);
  channel.select('owner', null); await settle(); channel.pulse(); await settle();
  assert.deepEqual(events.map((event) => [event.sequence, event.question_id]), [[1, 'q1'], [2, null], [3, null]]);
});

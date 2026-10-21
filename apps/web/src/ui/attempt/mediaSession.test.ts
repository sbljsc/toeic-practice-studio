import test from 'node:test';
import assert from 'node:assert/strict';
import { MediaSession, type MediaPosition } from './mediaSession.ts';
import type { Attempt } from '../../domain/types.ts';

class NativeAudio extends EventTarget {
  private source = ''; private time = 0;
  srcWrites = 0; seeks = 0; plays = 0; paused = true; readyState = 4; seeking = false;
  volume = 1; muted = false; playbackRate = 1;
  get src() { return this.source; }
  set src(value: string) { this.source = value; this.srcWrites++; }
  get currentTime() { return this.time; }
  set currentTime(value: number) { this.time = value; this.seeks++; }
  load() { this.pause(); }
  play() { this.plays++; this.paused = false; this.dispatchEvent(new Event('playing')); return Promise.resolve(); }
  pause() { if (!this.paused) { this.paused = true; this.dispatchEvent(new Event('pause')); } }
  advance(seconds: number) { if (!this.paused) this.time += seconds; this.dispatchEvent(new Event('timeupdate')); }
}
const item = (id: string, start: number, end: number, url = '/track.mp3') =>
  ({ id, url, asset_id: id, start_seconds: start, end_seconds: end, part: 2, exam_id: 'test-01', question_ids: [id] });
function attempt(extra: Partial<Attempt> = {}): Attempt {
  return { id: 'attempt', status: 'ready', mode: 'practice', audio_elapsed_ms: 0,
    audio_queue: [item('q7', 272, 292)], media_state: undefined,
    timing: { phase: 'practice' }, ...extra } as Attempt;
}
function setup() {
  const audio = new NativeAudio(); let now = 0;
  const saved: MediaPosition[] = [], interruptions: string[] = [];
  const session = new MediaSession(audio, { onState() {},
    onPersist(state) { saved.push(state); }, onInterrupt(reason) { interruptions.push(reason); } },
    () => now, .2, false);
  return { audio, saved, interruptions, session, advance(ms: number) { now += ms; } };
}
const flush = () => new Promise<void>((done) => queueMicrotask(done));

test('preflight proves playback, preserves quiet volume, and returns to the selected beginning', async () => {
  const { session, audio } = setup();
  session.update(attempt(), false);
  assert.equal(await session.unlock(), true);
  assert.equal(audio.volume, .2);
  assert.equal(audio.currentTime, 272);
  assert.equal(audio.paused, true);
  assert.equal(session.snapshot().authorized, true);
  session.destroy();
});

test('practice hydrates a saved later clip and persists normal playback progress', async () => {
  const h = setup();
  h.session.update(attempt({ status: 'running', audio_queue: [item('a', 10, 20), item('b', 100, 120, '/two.mp3')],
    media_state: { queue_index: 1, position_seconds: 3, playback_rate: 1.5 } }), true);
  await flush();
  assert.equal(h.audio.src, '/two.mp3'); assert.equal(h.audio.currentTime, 103);
  h.advance(1500); h.audio.advance(2);
  assert.equal(h.saved.at(-1)?.queue_index, 1);
  assert.equal(h.saved.at(-1)?.position_seconds, 5);
  assert.equal(h.saved.at(-1)?.playback_rate, 1.5);
  h.session.destroy();
});

test('routine practice DTO refresh does not seek or reassign src', async () => {
  const h = setup(), a = attempt({ status: 'running' });
  h.session.update(a, true); await flush();
  h.advance(1000); h.audio.advance(1);
  const before = { sources: h.audio.srcWrites, seeks: h.audio.seeks };
  h.session.update({ ...a, answers: {} }, true);
  assert.deepEqual({ sources: h.audio.srcWrites, seeks: h.audio.seeks }, before);
  h.session.destroy();
});

test('cross-asset playback resumes and the final selected clip actually stops', async () => {
  const h = setup();
  h.session.update(attempt({ status: 'running', audio_queue: [item('a', 10, 11), item('b', 100, 101, '/two.mp3')] }), true);
  await flush(); h.advance(1100); h.audio.advance(1.1); await flush();
  assert.equal(h.audio.src, '/two.mp3'); assert.equal(h.audio.paused, false);
  assert.equal(h.session.snapshot().queueIndex, 1);
  h.advance(1100); h.audio.advance(1.1);
  assert.equal(h.audio.paused, true); assert.equal(h.audio.currentTime, 101);
  assert.equal(h.session.snapshot().positionSeconds, 1);
  h.session.destroy();
});

test('buffer starvation is an interruption even while the browser says waiting', async () => {
  const h = setup(), a = attempt({ mode: 'exam', timing: { phase: 'listening' } as Attempt['timing'] });
  h.session.update(a, false); await h.session.unlock();
  h.session.update({ ...a, status: 'running' }, true); await flush();
  h.audio.dispatchEvent(new Event('waiting'));
  h.advance(5100); h.session.tick();
  assert.equal(h.interruptions.length, 1);
  assert.equal(h.session.snapshot().stalled, true);
  h.session.destroy();
});

test('paused practice cannot play, and the reading phase stops strict audio', async () => {
  const h = setup(), a = attempt({ status: 'paused' });
  h.session.update(a, true); assert.equal(await h.session.play(), false);
  const strict = attempt({ id: 'strict', status: 'ready', mode: 'exam', timing: { phase: 'listening' } as Attempt['timing'] });
  h.session.update(strict, false); await h.session.unlock();
  h.session.update({ ...strict, status: 'running' }, true); await flush();
  h.session.update({ ...strict, status: 'running', audio_elapsed_ms: 20000,
    timing: { phase: 'reading' } as Attempt['timing'] }, true);
  assert.equal(h.audio.paused, true); assert.equal(h.interruptions.length, 0);
  h.session.destroy();
});

test('media-state writes are ordered and coalesce to the latest intentional seek', async () => {
  const audio = new NativeAudio(); let now = 0;
  let release!: () => void;
  const gate = new Promise<void>((done) => { release = done; });
  const positions: number[] = [];
  const session = new MediaSession(audio, { onState() {}, onInterrupt() {},
    onPersist(position) { positions.push(position.position_seconds); return positions.length === 1 ? gate : Promise.resolve(); } },
    () => now, 0, false);
  session.update(attempt({ status: 'running' }), true); await flush();
  now = 1100; audio.advance(1);
  now = 2200; audio.advance(1);
  session.seek(.5);
  try { assert.deepEqual(positions, [1], 'only one media-state write may be in flight'); }
  finally { release(); }
  await flush(); await flush();
  assert.deepEqual(positions, [1, .5]);
  session.destroy();
});

test('reopening a workspace cannot let a retired session overwrite a newer seek', async () => {
  let release!: () => void;
  const gate = new Promise<void>((done) => { release = done; });
  const positions: number[] = [];
  const old = new MediaSession(new NativeAudio(), { onState() {}, onInterrupt() {},
    onPersist(state) { positions.push(state.position_seconds); return positions.length === 1 ? gate : undefined; } },
    () => 0, 0, false);
  const newer = new MediaSession(new NativeAudio(), { onState() {}, onInterrupt() {},
    onPersist(state) { positions.push(state.position_seconds); } }, () => 0, 0, false);
  const live = attempt({ id: 'cross-lifetime', status: 'running' });
  old.update(live, true); await flush(); old.seek(1); old.seek(2); old.destroy();
  newer.update(live, true); await flush(); newer.seek(9);
  const beforeAck = [...positions];
  release(); for (let i = 0; i < 8; i++) await flush();
  try {
    assert.deepEqual(beforeAck, [1], 'the reopened workspace must join the attempt writer');
    assert.equal(positions.at(-1), 9, `retired writes must not finish after the newer seek: ${positions}`);
  } finally { newer.destroy(); }
});

test('a custom or mixed Part exam plays strict audio within its single practice phase budget', async () => {
  for (const scope of ['custom', 'part'] as const) {
    const h = setup(), ready = attempt({ scope, mode: 'exam' });
    h.session.update(ready, false); assert.equal(await h.session.unlock(), true);
    const live = { ...ready, status: 'running' as const, audio_elapsed_ms: 0 };
    h.session.update(live, true); await flush();
    assert.equal(h.audio.paused, false, `${scope} strict audio must play`);
    h.advance(5000); h.audio.advance(5);
    h.session.update({ ...live, audio_elapsed_ms: 5000 }, true); h.session.tick();
    assert.equal(h.audio.currentTime, 277, 'resume derives from server elapsed, not stored seek');
    h.advance(3000); h.audio.advance(3); h.session.tick();
    assert.equal(h.session.snapshot().positionSeconds, 8);
    h.session.pause(); h.session.seek(0); h.session.setRate(2);
    assert.equal(h.audio.paused, false, 'exam keeps pause locked');
    assert.equal(h.audio.currentTime, 280, 'exam keeps seek locked');
    assert.equal(h.audio.playbackRate, 1);
    h.advance(13000); h.audio.advance(13); h.session.tick();
    assert.equal(h.audio.paused, true, 'selected clip ends without extending the selected budget');
    assert.deepEqual(h.interruptions, []);
    h.session.destroy();
  }
});

test('a full exam never enables audio outside its listening phase', async () => {
  const h = setup(), ready = attempt({ scope: 'full', mode: 'exam' });
  h.session.update(ready, false); await h.session.unlock();
  h.session.update({ ...ready, status: 'running' }, true); await flush();
  assert.equal(h.audio.paused, true);
  assert.equal(await h.session.play(), false);
  h.session.destroy();
});

test('selecting a question in another clip stops the previous clip', async () => {
  const h = setup();
  const first = { ...item('a', 10, 20), question_ids: ['qa'] };
  const shared = { ...item('b', 100, 120, '/two.mp3'), question_ids: ['qb1', 'qb2'] };
  h.session.update(attempt({ status: 'running', audio_queue: [first, shared] }), true);
  await flush();
  assert.equal(h.audio.src, '/track.mp3');
  h.session.selectQuestion('qb1');
  await flush();
  assert.equal(h.audio.src, '/two.mp3', 'the next clip must be loaded');
  assert.equal(h.session.snapshot().queueIndex, 1);
  assert.equal(h.audio.paused, false);
  h.session.destroy();
});

test('selecting a question in the same clip keeps playback running', async () => {
  const h = setup();
  const shared = { ...item('b', 100, 120, '/two.mp3'), question_ids: ['qb1', 'qb2'] };
  h.session.update(attempt({ status: 'running', audio_queue: [shared] }), true);
  await flush();
  h.audio.advance(5);
  const before = { src: h.audio.src, time: h.audio.currentTime, plays: h.audio.plays };
  h.session.selectQuestion('qb2');
  await flush();
  assert.equal(h.audio.src, before.src, 'the same clip must not be reloaded');
  assert.equal(h.audio.currentTime, before.time, 'the same clip must not be re-seeked');
  assert.equal(h.audio.paused, false, 'the same clip must keep playing');
  h.session.destroy();
});

test('selecting a question without audio stops the running clip', async () => {
  const h = setup();
  const first = { ...item('a', 10, 20), question_ids: ['qa'] };
  h.session.update(attempt({ status: 'running', audio_queue: [first] }), true);
  await flush();
  assert.equal(h.audio.paused, false);
  h.session.selectQuestion('reading-1');
  await flush();
  assert.equal(h.audio.paused, true, 'a question without audio must silence the previous clip');
  h.session.destroy();
});

test('returning to an audible question after a silent one resumes the same clip', async () => {
  const h = setup();
  const first = { ...item('a', 10, 20), question_ids: ['qa'] };
  h.session.update(attempt({ status: 'running', audio_queue: [first] }), true);
  await flush();
  assert.equal(h.audio.paused, false);
  h.session.selectQuestion('reading-1');
  await flush();
  assert.equal(h.audio.paused, true);
  // Coming back to the same clip must play again, not stay frozen.
  h.session.selectQuestion('qa');
  await flush();
  assert.equal(h.audio.paused, false, 'the clip must resume when its question is selected again');
  assert.equal(h.session.snapshot().queueIndex, 0);
  h.session.destroy();
});

test('resuming a silenced clip does not restart it from the beginning', async () => {
  const h = setup();
  const first = { ...item('a', 10, 20), question_ids: ['qa'] };
  h.session.update(attempt({ status: 'running', audio_queue: [first] }), true);
  await flush();
  h.audio.advance(5);
  const reached = h.audio.currentTime;
  h.session.selectQuestion('reading-1');
  await flush();
  h.session.selectQuestion('qa');
  await flush();
  assert.equal(h.audio.currentTime, reached, 'the clip must continue from where it stopped');
  h.session.destroy();
});

test('replay targets the current question or shared material and stops at its own boundary', async () => {
  const h = setup();
  const first = item('a', 10, 20);
  const shared = { ...item('b', 100, 120), question_ids: ['q32', 'q33', 'q34'] };
  h.session.update(attempt({ status: 'running', audio_queue: [first, shared, item('c', 200, 220)] }), true);
  await flush();
  assert.equal(await h.session.replayQuestion('q33'), true);
  assert.equal(h.audio.currentTime, 100);
  assert.equal(h.session.snapshot().queueIndex, 1);
  h.audio.advance(8);
  assert.equal(await h.session.replayQuestion('q34'), true, 'same material must restart too');
  assert.equal(h.audio.currentTime, 100);
  h.audio.advance(20.1); await flush();
  assert.equal(h.audio.paused, true);
  assert.equal(h.audio.currentTime, 120);
  assert.equal(h.session.snapshot().queueIndex, 1, 'replay must not continue into the next article');
  h.session.destroy();
});

test('replay is locked in exams and while practice is paused or read only', async () => {
  for (const [mode, status, allowed] of [['exam', 'running', true], ['practice', 'paused', true], ['practice', 'running', false]] as const) {
    const h = setup();
    h.session.update(attempt({ mode, status }), allowed); await flush();
    const position = h.audio.currentTime;
    assert.equal(await h.session.replayQuestion('q7'), false);
    assert.equal(h.audio.currentTime, position);
    h.session.destroy();
  }
});

test('sentence click uses absolute source position and starts playback without extending clip bounds', async () => {
  const h = setup(); h.session.update(attempt({status:'running'}),true); await flush();
  h.session.pause(); assert.equal(await h.session.playSentence(280),true);
  assert.equal(h.audio.currentTime,280); assert.equal(h.audio.paused,false);
  h.audio.advance(15); assert.equal(h.audio.currentTime,292); assert.equal(h.audio.paused,true);
  h.session.destroy();
});
test('sentence click rejects invalid positions, strict exams, paused timers and read-only pages', async () => {
  for (const [mode,status,allowed,position] of [['exam','running',true,280],['practice','paused',true,280],
    ['practice','running',false,280],['practice','running',true,271],['practice','running',true,292],
    ['practice','running',true,NaN]] as const) {
    const h=setup(); h.session.update(attempt({mode,status}),allowed); await flush();
    const before=h.audio.currentTime;
    assert.equal(await h.session.playSentence(position),false); assert.equal(h.audio.currentTime,before);
    h.session.destroy();
  }
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { ReviewPlayback } from './reviewPlayback.ts';

class Audio extends EventTarget {
  src = ''; currentTime = 0; playbackRate = 1; volume = 1; muted = false;
  readyState = 4; paused = true; loads = 0;
  load() { this.loads++; this.pause(); }
  removeAttribute(name: string) { if (name === 'src') this.src = ''; }
  play() { this.paused = false; this.dispatchEvent(new Event('playing')); return Promise.resolve(); }
  pause() { this.paused = true; this.dispatchEvent(new Event('pause')); }
  advance(seconds: number) { this.currentTime += seconds; this.dispatchEvent(new Event('timeupdate')); }
}
const item = (id: string, start: number, end: number) => ({id, url:'/track.mp3', asset_id:'track',
  start_seconds:start, end_seconds:end, part:3, exam_id:'test-01', question_ids:[id]});

test('review loads the exact segment without autoplay and supports pause, seek and replay', async () => {
  const audio = new Audio();
  const playback = new ReviewPlayback(audio, () => {}, false);
  playback.update([item('group', 100, 120)]);
  assert.equal(audio.currentTime, 100); assert.equal(audio.paused, true);
  await playback.play(); audio.advance(5); playback.pause();
  assert.equal(audio.paused, true); assert.equal(playback.snapshot().positionSeconds, 5);
  playback.seek(18); assert.equal(audio.currentTime, 118);
  playback.skip(10); assert.equal(audio.currentTime, 120);
  playback.skip(-10); assert.equal(audio.currentTime, 110);
  await playback.replay(); assert.equal(audio.currentTime, 100); assert.equal(audio.paused, false);
  playback.destroy();
});

test('destroy pauses playback and releases the old audio source', () => {
  const audio = new Audio();
  const playback = new ReviewPlayback(audio, () => {}, false);
  playback.update([item('group', 100, 120)]);
  void playback.play();
  playback.destroy();
  assert.equal(audio.paused, true);
  assert.equal(audio.src, '');
  assert.equal(audio.loads, 2, 'destroy reloads after clearing src to release the media resource');
});

test('review preserves the complete ending and stops before the next article', async () => {
  const audio = new Audio(); const playback = new ReviewPlayback(audio, () => {}, false);
  playback.update([item('a', 100, 120), item('b', 120, 140)]);
  await playback.play(); audio.advance(19.9);
  assert.equal(audio.paused, false, 'do not cut the last quarter second');
  audio.advance(.2);
  assert.equal(audio.paused, true); assert.equal(audio.currentTime, 120);
  assert.equal(playback.snapshot().index, 0);
  await playback.play(); assert.equal(audio.currentTime, 100);
  playback.destroy();
});

test('report rerenders do not reset position, and same-file segment changes seek to the new start', async () => {
  const audio = new Audio(); const playback = new ReviewPlayback(audio, () => {}, false);
  playback.update([item('a', 100, 120), item('b', 200, 220)]);
  await playback.play(); audio.advance(5);
  playback.update([item('a', 100, 120), item('b', 200, 220)]);
  assert.equal(audio.currentTime, 105); assert.equal(audio.loads, 1);
  playback.select(1); assert.equal(audio.currentTime, 200); assert.equal(audio.paused, true);
  playback.seek(-99); assert.equal(audio.currentTime, 200);
  playback.destroy();
});

test('metadata readiness preserves a seek requested before the file is ready', async () => {
  const audio = new Audio(); audio.readyState = 0;
  const playback = new ReviewPlayback(audio, () => {}, false);
  playback.update([item('a', 100, 120)]); playback.seek(7);
  audio.readyState = 4; audio.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(audio.currentTime, 107);
  playback.destroy();
});

test('an explicit focus change selects its clip while ordinary rerenders retain manual choice', () => {
  const audio = new Audio(); const playback = new ReviewPlayback(audio, () => {}, false);
  const queue = [item('a', 100, 120), item('b', 200, 220)];
  playback.update(queue, 0); playback.update(queue, 1);
  assert.equal(audio.currentTime, 200);
  playback.select(0); playback.update([...queue], 1);
  assert.equal(audio.currentTime, 100, 'a rerender does not override manual selection');
  playback.destroy();
});

test('a review sentence click seeks in the source file and resumes from that exact sentence', async () => {
  const audio = new Audio(); const playback = new ReviewPlayback(audio, () => {}, false);
  playback.update([item('a',100,120)]);
  await playback.playSentence(108);
  assert.equal(audio.currentTime,108); assert.equal(audio.paused,false);
  playback.pause(); await playback.playSentence(99);
  assert.equal(audio.currentTime,108); assert.equal(audio.paused,true);
  await playback.playSentence(NaN); assert.equal(audio.currentTime,108);
  playback.destroy();
});

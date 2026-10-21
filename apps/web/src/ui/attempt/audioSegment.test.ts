import test from 'node:test';
import assert from 'node:assert/strict';
import { audioSegmentIndex, keepsSameAudioSegment } from './audioSegment.ts';

const queue = [
  { question_ids: ['q1'] },
  { question_ids: ['q2', 'q3', 'q4'] },
  { question_ids: ['q5'] },
];

test('a question maps to the clip that actually carries it', () => {
  assert.equal(audioSegmentIndex(queue, 'q1'), 0);
  assert.equal(audioSegmentIndex(queue, 'q3'), 1);
  assert.equal(audioSegmentIndex(queue, 'q5'), 2);
});

test('a question without audio has no segment', () => {
  assert.equal(audioSegmentIndex(queue, 'reading-1'), -1);
  assert.equal(audioSegmentIndex([], 'q1'), -1);
  assert.equal(audioSegmentIndex(undefined, 'q1'), -1);
});

test('questions sharing one clip keep the same segment', () => {
  assert.equal(keepsSameAudioSegment(queue, 'q2', 'q3'), true);
  assert.equal(keepsSameAudioSegment(queue, 'q3', 'q4'), true);
});

test('moving between different clips changes the segment', () => {
  assert.equal(keepsSameAudioSegment(queue, 'q1', 'q2'), false);
  assert.equal(keepsSameAudioSegment(queue, 'q4', 'q5'), false);
});

test('a question without audio never keeps the previous clip playing', () => {
  assert.equal(keepsSameAudioSegment(queue, 'q1', 'reading-1'), false);
  assert.equal(keepsSameAudioSegment(queue, 'reading-1', 'reading-2'), false);
});

test('an unknown previous question cannot keep playback', () => {
  assert.equal(keepsSameAudioSegment(queue, undefined, 'q2'), false);
  assert.equal(keepsSameAudioSegment(queue, 'gone', 'q2'), false);
});

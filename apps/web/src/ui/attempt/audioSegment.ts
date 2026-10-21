import type { Attempt } from '../../domain/types';

/** One audio clip in the attempt queue, with the questions it covers. */
export interface QueueItem {
  question_ids?: string[];
}

/**
 * Index of the audio clip that carries a question, or -1 when the question
 * has no audio. A clip may cover several questions (one dialogue or
 * monologue), so the mapping is many-to-one and must never be guessed from
 * question order.
 */
export function audioSegmentIndex(queue: readonly QueueItem[] | undefined, questionId: string): number {
  if (!queue?.length) return -1;
  return queue.findIndex((item) => item.question_ids?.includes(questionId) ?? false);
}

/**
 * Whether moving from one question to another keeps the same audio clip.
 * Same clip means playback continues where it is; a different clip means the
 * previous clip must stop. Questions without audio never keep playback.
 */
export function keepsSameAudioSegment(
  queue: readonly QueueItem[] | undefined,
  fromQuestionId: string | undefined,
  toQuestionId: string,
): boolean {
  if (!fromQuestionId) return false;
  const from = audioSegmentIndex(queue, fromQuestionId);
  if (from < 0) return false;
  return from === audioSegmentIndex(queue, toQuestionId);
}

/** The audio queue of an attempt, when it exposes one. */
export function attemptAudioQueue(attempt: Pick<Attempt, 'audio_queue'> | undefined): readonly QueueItem[] {
  return attempt?.audio_queue ?? [];
}

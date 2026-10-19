import type { Attempt, AudioQueueItem, ListeningScript, SubtitleSentence } from '../domain/types.ts';

export function selectionTouchesSentence(selection: Selection | null, row: Node): boolean {
  if (!selection || selection.isCollapsed) return false;
  for (let index = 0; index < selection.rangeCount; index++) {
    try { if (selection.getRangeAt(index).intersectsNode(row)) return true; }
    catch { return true; }
  }
  return false;
}

export function validSentences(script: ListeningScript, clip?: AudioQueueItem): SubtitleSentence[] {
  const sentences = script.sentences ?? [];
  if (!clip || !Number.isFinite(clip.start_seconds) || !Number.isFinite(clip.end_seconds)) return [];
  let end = clip.start_seconds;
  const ids = new Set<string>();
  for (const cue of sentences) {
    if (!cue.id || ids.has(cue.id) || !cue.text.trim() || !Number.isFinite(cue.start_seconds) ||
        !Number.isFinite(cue.end_seconds) || cue.start_seconds < end ||
        cue.start_seconds >= cue.end_seconds || cue.end_seconds > clip.end_seconds) return [];
    ids.add(cue.id); end = cue.end_seconds;
  }
  return sentences;
}

/** Source-absolute native media time, not the countdown or wall time. */
export function activeSentenceId(sentences: SubtitleSentence[], sourceTime: number): string | null {
  if (!Number.isFinite(sourceTime)) return null;
  let low = 0, high = sentences.length - 1;
  while (low <= high) {
    const mid = (low + high) >>> 1;
    if (sourceTime < sentences[mid].start_seconds) high = mid - 1;
    else if (sourceTime >= sentences[mid].end_seconds) low = mid + 1;
    else return sentences[mid].id;
  }
  return null;
}

export function practiceSubtitleContext(attempt: Attempt, queueIndex: number) {
  if (attempt.mode !== 'practice' || !['running', 'paused'].includes(attempt.status)) return null;
  const clip = attempt.audio_queue[queueIndex];
  if (!clip) return null;
  const group = attempt.groups.find((item) => item.section === 'listening' &&
    item.question_ids.length === clip.question_ids.length &&
    item.question_ids.every((id) => clip.question_ids.includes(id)));
  return group?.listening_script ? { group, clip, script: group.listening_script } : null;
}

export function followScrollTop({ scrollTop, viewportHeight, scrollHeight, rowTop, rowHeight }: {
  scrollTop: number; viewportHeight: number; scrollHeight: number; rowTop: number; rowHeight: number;
}): number | null {
  if (rowTop >= scrollTop && rowTop + rowHeight <= scrollTop + viewportHeight) return null;
  return Math.max(0, Math.min(scrollHeight - viewportHeight, rowTop + rowHeight / 2 - viewportHeight / 2));
}

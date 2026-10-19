// Pure clip math for review replay. A selected segment must start at its own
// cue offset, not at 0 of the shared source file.

export interface ClipSegment {
  start_seconds: number;
  end_seconds: number;
}

export function segmentDuration(segment: ClipSegment | null | undefined): number {
  if (!segment) return 0;
  return Math.max(0, segment.end_seconds - segment.start_seconds);
}

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

/** Absolute source time for a position within the selected clip. */
export function sourceTimeFor(segment: ClipSegment | null | undefined, offsetSeconds: number): number {
  if (!segment) return 0;
  return segment.start_seconds + clamp(offsetSeconds, 0, segmentDuration(segment));
}

/** Clip-relative position from an absolute source time, clamped to the clip. */
export function offsetFor(segment: ClipSegment | null | undefined, sourceTime: number): number {
  if (!segment) return 0;
  return clamp(sourceTime - segment.start_seconds, 0, segmentDuration(segment));
}

/** True once playback has reached (or passed) the clip's end boundary. */
export function reachedClipEnd(segment: ClipSegment | null | undefined, sourceTime: number): boolean {
  const duration = segmentDuration(segment);
  if (duration <= 0) return false;
  return sourceTime >= segment!.end_seconds;
}

export const REVIEW_RATES = [0.75, 1, 1.25, 1.5, 2] as const;

export function clampRate(rate: number): number {
  return clamp(rate, 0.5, 2);
}

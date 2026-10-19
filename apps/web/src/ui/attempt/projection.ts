// Pure audio projection/boundary math, extracted from the media controller so
// it can be regression-tested without a live <audio> element. Strict exam
// position is derived ONLY from the server's audio_elapsed_ms projected with a
// monotonic clock; nothing here mutates server state or trusts client media.

export interface QueueSegment {
  id: string;
  url: string;
  start_seconds: number;
  end_seconds: number;
}

export interface SegmentPlan {
  index: number;
  segment: QueueSegment;
  /** Absolute seconds in the source file where this segment begins. */
  sourceStart: number;
  /** Seconds of audio this segment contributes to the queue. */
  durationSeconds: number;
  /** Cumulative queue seconds before this segment starts. */
  queueOffsetSeconds: number;
}

export interface QueuePlan {
  segments: SegmentPlan[];
  totalSeconds: number;
}

export function buildQueuePlan(queue: QueueSegment[]): QueuePlan {
  const segments: SegmentPlan[] = [];
  let cumulative = 0;
  for (const segment of queue) {
    const durationSeconds = Math.max(0, segment.end_seconds - segment.start_seconds);
    segments.push({
      index: segments.length,
      segment,
      sourceStart: segment.start_seconds,
      durationSeconds,
      queueOffsetSeconds: cumulative,
    });
    cumulative += durationSeconds;
  }
  return { segments, totalSeconds: cumulative };
}

/**
 * Resolve which queue segment a queue-relative elapsed time falls in and how
 * far into that segment it is. Handles cross-test queues and Part 2 style
 * non-zero starts because it only ever uses the selected segments' durations,
 * never the source file's absolute timeline.
 */
export function resolveQueuePosition(
  plan: QueuePlan,
  queueElapsedSeconds: number,
): { plan: SegmentPlan; offsetSeconds: number } | null {
  if (plan.segments.length === 0) return null;
  if (queueElapsedSeconds <= 0) {
    return { plan: plan.segments[0], offsetSeconds: 0 };
  }
  for (const entry of plan.segments) {
    const segmentEnd = entry.queueOffsetSeconds + entry.durationSeconds;
    // Half-open [start, end) so boundary values land on the following segment.
    if (queueElapsedSeconds < segmentEnd) {
      return { plan: entry, offsetSeconds: queueElapsedSeconds - entry.queueOffsetSeconds };
    }
  }
  const last = plan.segments[plan.segments.length - 1];
  return { plan: last, offsetSeconds: last.durationSeconds };
}

export function absoluteSourceTime(plan: QueuePlan, queueElapsedSeconds: number): number | null {
  const resolved = resolveQueuePosition(plan, queueElapsedSeconds);
  if (!resolved || !resolved.plan) return null;
  return resolved.plan.sourceStart + clamp(resolved.offsetSeconds, 0, resolved.plan.durationSeconds);
}

/**
 * Project the queue position from the last server sync. `perfAtSync` and `now`
 * are performance.now() samples taken at the same instant the server elapsed
 * value was received, so client wall-clock changes cannot move exam audio.
 */
export function projectQueueElapsed(
  audioElapsedMsAtSync: number,
  perfAtSync: number,
  now: number,
): number {
  const driftSeconds = Math.max(0, (now - perfAtSync) / 1000);
  return Math.max(0, audioElapsedMsAtSync / 1000 + driftSeconds);
}

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

export const STALL_THRESHOLD_MS = 5000;

export interface StallDecision {
  stalled: boolean;
  shouldReport: boolean;
}

/**
 * A strict-exam stall means no measurable playback progress for the threshold
 * while audio is expected to be running. Playback rate, currentTime movement,
 * and buffering state all count as progress; merely having played is not.
 */
export function evaluateStall(input: {
  running: boolean;
  waiting: boolean;
  currentTimeMs: number;
  lastProgressTimeMs: number;
  lastProgressPosition: number;
  nowMs: number;
  alreadyReported: boolean;
}): StallDecision {
  if (!input.running) {
    return { stalled: false, shouldReport: false };
  }
  const advanced = Math.abs(input.currentTimeMs - input.lastProgressPosition) >= 250;
  if (advanced) {
    return { stalled: false, shouldReport: false };
  }
  const idleMs = input.nowMs - Math.max(input.lastProgressTimeMs, input.nowMs - STALL_THRESHOLD_MS);
  const stalled = input.nowMs - input.lastProgressTimeMs >= STALL_THRESHOLD_MS;
  return { stalled, shouldReport: stalled && !input.alreadyReported && idleMs >= 0 };
}

/**
 * Guard the native element at a segment's clip end. Browsers only fire
 * `ended` for a whole file, so a Part 1 clip would otherwise bleed into Part 2
 * and custom groups would play the remainder of the MP3.
 */
export function needsBoundaryAdvance(input: {
  positionSeconds: number;
  segmentDurationSeconds: number;
  driftToleranceSeconds?: number;
}): boolean {
  const tolerance = input.driftToleranceSeconds ?? 0.25;
  if (input.segmentDurationSeconds <= 0) return false;
  return input.positionSeconds >= input.segmentDurationSeconds - tolerance;
}

import { useEffect, useRef, useState } from 'react';
import type { AttemptStatus, AttemptTiming } from './types';
import { projectClock, type ClockSnapshot, type ProjectedClock } from './clockProjection';

export type { ProjectedClock };

const IDLE: ProjectedClock = { display: '—', remainingMs: null, elapsedMs: 0, expired: false };

function isFrozen(status: AttemptStatus | undefined, timing: AttemptTiming | null): boolean {
  if (!timing) return true;
  if (timing.phase === 'finished') return true;
  return status === undefined || status === 'ready' || status === 'submitted' || status === 'expired' || status === 'paused';
}

/**
 * Projects the server-authoritative clock from a monotonic anchor. A paused,
 * ready, closed or finished attempt stops accruing drift between syncs, so the
 * displayed value equals the last server snapshot rather than drifting until
 * the next 5s sync.
 */
export function useProjectedClock(timing: AttemptTiming | null, status?: AttemptStatus): ProjectedClock {
  const [snapshot, setSnapshot] = useState<ClockSnapshot | null>(null);
  const [now, setNow] = useState(() => performance.now());
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!timing) {
      setSnapshot(null);
      return;
    }
    // Take the anchor and the sample together so drift can never go negative.
    const perfAtSync = performance.now();
    setSnapshot({
      perfAtSync,
      remainingMs: timing.remaining_ms,
      elapsedMs: timing.elapsed_ms,
    });
    setNow(perfAtSync);
  }, [timing]);

  const frozen = isFrozen(status, timing);

  useEffect(() => {
    // Only a live countdown/countup needs repainting.
    if (!timing || frozen || timing.kind === 'none') return;
    const repaint = () => setNow(performance.now());
    timerRef.current = window.setInterval(repaint, 100);
    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [frozen, timing]);

  if (!timing || !snapshot) return IDLE;
  return projectClock(
    { kind: timing.kind, isPaused: timing.is_paused, frozen },
    snapshot,
    now,
  );
}

export function formatMs(ms: number | null): string {
  return ms === null ? '—' : projectClock({ kind: 'countdown', isPaused: false, frozen: false }, {
    perfAtSync: 0,
    remainingMs: ms,
    elapsedMs: 0,
  }, 0).display;
}

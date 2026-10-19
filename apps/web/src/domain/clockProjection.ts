// Pure timer projection. The server owns every deadline; we snapshot
// performance.now() at each sync and repaint from that monotonic anchor.
// Nothing here decrements a stateful counter, and a paused/ready/closed attempt
// must not accrue drift between 5s syncs.

export interface ClockSnapshot {
  perfAtSync: number;
  remainingMs: number | null;
  elapsedMs: number;
}

export interface ProjectedClock {
  display: string;
  remainingMs: number | null;
  elapsedMs: number;
  expired: boolean;
}

export function formatClockMs(ms: number): string {
  const clamped = Math.max(0, ms);
  const totalSeconds = Math.floor(clamped / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const mm = String(minutes).padStart(2, '0');
  const ss = String(seconds).padStart(2, '0');
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

export interface ProjectionInput {
  kind: 'countdown' | 'countup' | 'none';
  /** True while the attempt is paused; the projection must freeze. */
  isPaused: boolean;
  /** Ready/paused/closed/submitted/expired all stop accruing elapsed time. */
  frozen: boolean;
}

export function projectClock(input: ProjectionInput, snapshot: ClockSnapshot, now: number): ProjectedClock {
  if (input.kind === 'none') {
    return { display: '—', remainingMs: null, elapsedMs: snapshot.elapsedMs, expired: false };
  }
  // Negative drift means `now` predates the recorded sync sample (a fresh
  // snapshot rendered before the first repaint). Clamp so a reload never shows
  // a countdown that has grown by up to a sync interval.
  const drift = Math.max(0, now - snapshot.perfAtSync);

  // A paused attempt shows exactly what the server last reported.
  if (input.isPaused || input.frozen) {
    return {
      display: input.kind === 'countup' ? formatClockMs(snapshot.elapsedMs) : formatClockMs(snapshot.remainingMs ?? 0),
      remainingMs: input.kind === 'countdown' ? snapshot.remainingMs : null,
      elapsedMs: snapshot.elapsedMs,
      expired: input.kind === 'countdown' && snapshot.remainingMs === 0,
    };
  }

  if (input.kind === 'countdown') {
    const remainingMs = snapshot.remainingMs === null ? null : Math.max(0, snapshot.remainingMs - drift);
    return {
      display: formatClockMs(remainingMs ?? 0),
      remainingMs,
      elapsedMs: snapshot.elapsedMs + drift,
      expired: remainingMs === 0,
    };
  }

  const elapsedMs = snapshot.elapsedMs + drift;
  return { display: formatClockMs(elapsedMs), remainingMs: null, elapsedMs, expired: false };
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../domain/http.ts';
import type { UpdateStatus } from '../domain/types.ts';

export type UpdatePhase =
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'ready'
  | 'current'
  | 'error'
  | 'unsupported'
  | 'installing';

/** What the indicator says, and whether it can be clicked. */
export function updateBadge(state: UpdateStatus): {
  label: string;
  tone: 'info' | 'muted' | 'warn' | 'good';
  clickable: boolean;
  percent: number | null;
} {
  const phase = (state.phase ?? 'idle') as UpdatePhase;
  if (phase === 'downloading') {
    const total = state.total_bytes ?? 0;
    const done = state.downloaded_bytes ?? 0;
    const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null;
    return {
      label: percent === null ? '下载中…' : `下载中 ${percent}%`,
      tone: 'info',
      clickable: false,
      percent,
    };
  }
  if (phase === 'ready') {
    return { label: '待重启', tone: 'warn', clickable: true, percent: 100 };
  }
  if (phase === 'available') {
    return { label: '可更新', tone: 'info', clickable: true, percent: null };
  }
  if (phase === 'checking') {
    return { label: '检查更新…', tone: 'muted', clickable: false, percent: null };
  }
  if (phase === 'error') {
    return { label: '更新失败', tone: 'bad' as 'warn', clickable: true, percent: null };
  }
  if (phase === 'installing') {
    return { label: '正在重启…', tone: 'muted', clickable: false, percent: null };
  }
  return { label: '', tone: 'muted', clickable: false, percent: null };
}

/**
 * Keeps the update state fresh.
 *
 * The check is done once when the page opens, and the download is started
 * in the background when a new release is found, so a release is usually
 * already on disk by the time the learner notices the badge.
 */
export function useUpdateIndicator(enabled: boolean) {
  const [state, setState] = useState<UpdateStatus | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      setState(await api.updateStatus());
    } catch {
      // The indicator is a convenience; its absence must not break the page.
    }
  }, []);

  const check = useCallback(async () => {
    try {
      setState(await api.checkUpdate());
    } catch {
      // Ignored on purpose.
    }
  }, []);

  const startDownload = useCallback(async () => {
    try {
      setState(await api.startUpdateDownload());
    } catch {
      // Ignored on purpose.
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    void check();
    return undefined;
  }, [enabled, check]);

  useEffect(() => {
    if (!enabled) return undefined;
    const phase = state?.phase;
    if (phase === 'downloading' || phase === 'checking') {
      timer.current = window.setInterval(() => void refresh(), 700);
      return () => {
        if (timer.current) window.clearInterval(timer.current);
      };
    }
    return undefined;
  }, [enabled, state?.phase, refresh]);

  // A new release is fetched in the background so it is ready when wanted.
  useEffect(() => {
    if (state?.phase === 'available') void startDownload();
  }, [state?.phase, startDownload]);

  return { state, check, startDownload, refresh };
}

export function updateErrorText(error: unknown): string {
  return error instanceof ApiError ? error.message : '更新操作失败。';
}
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Attempt } from '../../domain/types';
import { MediaSession, type AudioControllerState, type MediaPosition } from './mediaSession';
export type { AudioControllerState } from './mediaSession';

interface Options {
  attempt: Attempt;
  active: boolean;
  onPracticeMediaState: (state: MediaPosition, attemptId?: string) => void | Promise<void>;
  onStall: (reason: string, attemptId?: string) => void;
}
function storedVolume(): number {
  try {
    const value = window.localStorage.getItem('toeic.volume');
    return value === null ? 1 : Math.min(1, Math.max(0, Number(value) || 0));
  } catch { return 1; }
}
function emptyState(): AudioControllerState {
  return { authorized: false, playing: false, queueIndex: 0, positionSeconds: 0,
    durationSeconds: 0, queueTotalSeconds: 0, playbackRate: 1,
    volume: storedVolume(), muted: false, stalled: false, waiting: false,
    needsResume: false, error: null };
}
export function useAudioController(options: Options) {
  const elementRef = useRef<HTMLAudioElement | null>(null);
  const session = useRef<MediaSession | null>(null);
  const latest = useRef(options); latest.current = options;
  const [state, setState] = useState<AudioControllerState>(emptyState);
  useEffect(() => {
    const element = elementRef.current;
    if (!element) {
      if (session.current) { session.current.destroy(); session.current = null; setState(emptyState()); }
      return;
    }
    if (!session.current || session.current.element !== element) {
      session.current?.destroy();
      session.current = new MediaSession(element, { onState: setState,
        onPersist: (position, id) => latest.current.onPracticeMediaState(position, id),
        onInterrupt: (reason, id) => latest.current.onStall(reason, id) },
        () => performance.now(), storedVolume());
    }
    session.current.update(options.attempt, options.active);
  }, [options.attempt, options.active]);
  useEffect(() => {
    const leave = () => session.current?.leave();
    window.addEventListener('pagehide', leave);
    return () => {
      window.removeEventListener('pagehide', leave);
      session.current?.leave(); session.current?.destroy(); session.current = null;
    };
  }, []);

  const unlock = useCallback(() => session.current?.unlock() ?? Promise.resolve(false), []);
  const play = useCallback(() => session.current?.play() ?? Promise.resolve(false), []);
  const pause = useCallback(() => session.current?.pause(), []);
  const seek = useCallback((seconds: number) => session.current?.seek(seconds), []);
  const setRate = useCallback((rate: number) => session.current?.setRate(rate), []);
  const selectQuestion = useCallback((id: string) => session.current?.selectQuestion(id), []);
  const replayQuestion = useCallback((id: string) => session.current?.replayQuestion(id) ?? Promise.resolve(false), []);
  const playSentence = useCallback((sourceTime: number) => session.current?.playSentence(sourceTime) ?? Promise.resolve(false), []);
  const setVolume = useCallback((volume: number) => {
    session.current?.setVolume(volume);
    try { window.localStorage.setItem('toeic.volume', String(volume)); } catch { /* session volume still works */ }
  }, []);
  const toggleMuted = useCallback(() => session.current?.toggleMuted(), []);
  return { state, elementRef, unlock, play, pause, seek, setRate, setVolume,
    toggleMuted, selectQuestion, replayQuestion, playSentence, resumeAfterInterruption: play };
}

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AudioQueueItem } from '../../domain/types';
import { initialReviewState, ReviewPlayback } from './reviewPlayback';

export { REVIEW_RATES } from './reviewClip';

export function useReviewAudio(queue: AudioQueueItem[], initialIndex = 0) {
  const elementRef = useRef<HTMLAudioElement | null>(null);
  const session = useRef<ReviewPlayback | null>(null);
  const latest = useRef({ queue, initialIndex }); latest.current = { queue, initialIndex };
  const [state, setState] = useState(initialReviewState);
  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;
    const playback = new ReviewPlayback(element, setState);
    session.current = playback;
    playback.update(latest.current.queue, latest.current.initialIndex);
    try {
      const saved = window.localStorage.getItem('toeic.volume');
      if (saved !== null) playback.setVolume(Number(saved) || 0);
    } catch { /* Browser storage is optional. */ }
    return () => { playback.destroy(); session.current = null; };
  }, []);
  useEffect(() => { session.current?.update(queue, initialIndex); }, [queue, initialIndex]);
  const toggle = useCallback((index: number) => session.current?.select(index), []);
  const play = useCallback(() => session.current?.play() ?? Promise.resolve(), []);
  const replay = useCallback(() => session.current?.replay() ?? Promise.resolve(), []);
  const playSentence = useCallback((sourceTime: number) => session.current?.playSentence(sourceTime) ?? Promise.resolve(), []);
  const pause = useCallback(() => session.current?.pause(), []);
  const seek = useCallback((seconds: number) => session.current?.seek(seconds), []);
  const skip = useCallback((seconds: number) => session.current?.skip(seconds), []);
  const setRate = useCallback((rate: number) => session.current?.setRate(rate), []);
  const next = useCallback(() => session.current?.select((session.current?.snapshot().index ?? 0) + 1), []);
  const previous = useCallback(() => session.current?.select((session.current?.snapshot().index ?? 0) - 1), []);
  const toggleMuted = useCallback(() => session.current?.toggleMuted(), []);
  const setVolume = useCallback((value: number) => {
    session.current?.setVolume(value);
    try { window.localStorage.setItem('toeic.volume', String(value)); } catch { /* Session volume still works. */ }
  }, []);
  return { state, elementRef, toggle, play, replay, playSentence, pause, seek, skip, setRate, next, previous, toggleMuted, setVolume };
}

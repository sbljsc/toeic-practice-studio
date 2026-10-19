import type { AudioQueueItem } from '../../domain/types.ts';
import { clamp, clampRate, offsetFor, reachedClipEnd, segmentDuration, sourceTimeFor } from './reviewClip.ts';

export interface ReviewAudioState {
  index: number; playing: boolean; positionSeconds: number; durationSeconds: number;
  rate: number; volume: number; muted: boolean; error: string | null; loading: boolean;
}
interface ReviewElement extends EventTarget {
  src: string; currentTime: number; playbackRate: number; volume: number; muted: boolean;
  readonly readyState: number; readonly paused: boolean;
  play(): Promise<void>; pause(): void; load(): void; removeAttribute(name: string): void;
}
export function initialReviewState(): ReviewAudioState {
  return { index: 0, playing: false, positionSeconds: 0, durationSeconds: 0,
    rate: 1, volume: 1, muted: false, error: null, loading: false };
}

/** Read-only media session. A clip always stops at its own end, never chains. */
export class ReviewPlayback {
  private queue: AudioQueueItem[] = [];
  private state = initialReviewState();
  private identity = '';
  private requestedIndex: number | null = null;
  private generation = 0;
  private stopped = false;
  private lastSnapshot = '';
  private timer: ReturnType<typeof setInterval> | null = null;
  private handlers: Record<string, EventListener>;
  private element: ReviewElement;
  private onState: (state: ReviewAudioState) => void;

  constructor(element: ReviewElement, onState: (state: ReviewAudioState) => void, autoTick = true) {
    this.element = element; this.onState = onState;
    this.handlers = {
      loadedmetadata: () => this.position(),
      timeupdate: () => this.tick(),
      ended: () => this.tick(),
      playing: () => { this.state.playing = true; this.state.loading = false; this.emit(); },
      pause: () => { this.state.playing = false; this.emit(); },
      waiting: () => { this.state.loading = true; this.emit(); },
      canplay: () => { this.state.loading = false; this.emit(); },
      error: () => { this.state.error = '音频加载失败，请重试。'; this.state.loading = false; this.emit(); },
    };
    for (const [event, handler] of Object.entries(this.handlers)) element.addEventListener(event, handler);
    if (autoTick) this.timer = setInterval(() => this.tick(), 50);
  }
  snapshot(): ReviewAudioState { return { ...this.state }; }
  private current(): AudioQueueItem | undefined { return this.queue[this.state.index]; }
  private emit(): void {
    const snapshot = this.snapshot(); const signature = JSON.stringify(snapshot);
    if (!this.stopped && signature !== this.lastSnapshot) {
      this.lastSnapshot = signature; this.onState(snapshot);
    }
  }
  update(queue: AudioQueueItem[], initialIndex = 0): void {
    this.queue = queue;
    const focusChanged = initialIndex !== this.requestedIndex;
    this.requestedIndex = initialIndex;
    this.select(focusChanged ? initialIndex : this.state.index);
  }
  select(index: number): void {
    const next = clamp(index, 0, Math.max(0, this.queue.length - 1));
    const current = this.queue[next];
    const identity = current ? JSON.stringify([current.id, current.url, current.start_seconds, current.end_seconds]) : '';
    if (identity === this.identity) return;
    this.generation++; this.element.pause(); this.identity = identity;
    this.state = { ...this.state, index: next, playing: false, positionSeconds: 0,
      durationSeconds: segmentDuration(current), error: null, loading: false };
    if (current) {
      if (this.element.src !== current.url && !this.element.src.endsWith(current.url)) {
        this.element.src = current.url; this.element.load();
      }
      this.element.playbackRate = this.state.rate;
      this.position();
    }
    this.emit();
  }
  private position(): void {
    if (this.element.readyState < 1 || !this.current()) return;
    try { this.element.currentTime = sourceTimeFor(this.current(), this.state.positionSeconds); }
    catch { /* loadedmetadata retries pending positioning */ }
  }
  tick(): void {
    const current = this.current();
    if (!current || this.element.readyState < 1 || this.stopped) return;
    if (reachedClipEnd(current, this.element.currentTime)) {
      this.element.pause(); this.state.playing = false;
      this.state.positionSeconds = this.state.durationSeconds; this.position();
    } else this.state.positionSeconds = offsetFor(current, this.element.currentTime);
    this.emit();
  }
  async play(): Promise<void> {
    if (!this.current() || this.stopped) return;
    if (this.state.positionSeconds >= this.state.durationSeconds) this.seek(0);
    this.position(); this.element.playbackRate = this.state.rate;
    const generation = this.generation;
    try {
      await this.element.play();
      if (this.stopped || generation !== this.generation) return;
      this.state.playing = !this.element.paused; this.state.error = null;
    } catch {
      if (this.stopped || generation !== this.generation) return;
      this.state.error = '播放未能开始，请再点一次播放。'; this.state.playing = false;
    }
    this.emit();
  }
  pause(): void { this.element.pause(); this.state.playing = false; this.emit(); }
  seek(seconds: number): void {
    this.state.positionSeconds = clamp(seconds, 0, this.state.durationSeconds); this.position();
    if (this.state.positionSeconds >= this.state.durationSeconds) this.pause();
    this.emit();
  }
  skip(seconds: number): void { this.seek(this.state.positionSeconds + seconds); }
  replay(): Promise<void> { this.seek(0); return this.play(); }
  playSentence(sourceTime: number): Promise<void> {
    const current = this.current();
    if (!current || !Number.isFinite(sourceTime) || sourceTime < current.start_seconds ||
        sourceTime >= current.end_seconds) return Promise.resolve();
    this.seek(sourceTime - current.start_seconds);
    return this.play();
  }
  setRate(rate: number): void { this.state.rate = clampRate(rate); this.element.playbackRate = this.state.rate; this.emit(); }
  setVolume(volume: number): void { this.state.volume = clamp(volume, 0, 1); this.element.volume = this.state.volume; this.emit(); }
  toggleMuted(): void { this.state.muted = !this.state.muted; this.element.muted = this.state.muted; this.emit(); }
  destroy(): void {
    this.stopped = true; this.generation++;
    if (this.timer) clearInterval(this.timer);
    for (const [event, handler] of Object.entries(this.handlers)) this.element.removeEventListener(event, handler);
    this.element.pause();
    this.element.removeAttribute('src');
    this.element.load();
  }
}

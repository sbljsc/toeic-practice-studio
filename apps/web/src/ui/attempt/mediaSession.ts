import type { Attempt } from '../../domain/types';
import { buildQueuePlan, clamp, resolveQueuePosition, STALL_THRESHOLD_MS, type QueuePlan } from './projection.ts';
import { mediaPersistence } from './mediaPersistence.ts';

export interface AudioControllerState {
  authorized: boolean; playing: boolean; queueIndex: number; positionSeconds: number;
  durationSeconds: number; queueTotalSeconds: number; playbackRate: number;
  volume: number; muted: boolean; stalled: boolean; waiting: boolean;
  needsResume: boolean; error: string | null;
}
export interface MediaPosition { queue_index: number; position_seconds: number; playback_rate: number }
export interface AudioElementLike extends EventTarget {
  src: string; currentTime: number; playbackRate: number; volume: number; muted: boolean;
  readonly paused: boolean; readonly readyState: number; readonly seeking: boolean;
  play(): Promise<void>; pause(): void; load(): void;
}
interface Callbacks {
  onState: (state: AudioControllerState) => void;
  onPersist: (state: MediaPosition, attemptId?: string) => void | Promise<void>;
  onInterrupt: (reason: string, attemptId?: string) => void;
}

/** One persistent native element, independent of React render/sync frequency. */
export class MediaSession {
  private attempt: Attempt | null = null;
  private plan: QueuePlan = { segments: [], totalSeconds: 0 };
  private allowed = false;
  private id = '';
  private anchor = { elapsed: 0, at: 0 };
  private source = '';
  private selectedIndex = -1;
  private holdingBoundary = false;
  private generation = 0;
  private loading = false;
  private userPaused = false;
  private replayOnly = false;
  private preflight = false;
  private stopped = false;
  private interrupted = false;
  private progressAt = 0;
  private observedPosition = 0;
  private persistedAt = -Infinity;
  private lastSnapshot = '';
  private timer: ReturnType<typeof setInterval> | null = null;
  private playRequest: Promise<boolean> | null = null;
  private state: AudioControllerState;
  private readonly handlers: Record<string, EventListener>;
  readonly element: AudioElementLike;
  private callbacks: Callbacks;
  private now: () => number;

  constructor(element: AudioElementLike, callbacks: Callbacks,
    now = () => performance.now(), volume = 1, autoTick = true) {
    this.element = element; this.callbacks = callbacks; this.now = now;
    this.state = { authorized: false, playing: false, queueIndex: 0, positionSeconds: 0,
      durationSeconds: 0, queueTotalSeconds: 0, playbackRate: 1, volume, muted: false,
      stalled: false, waiting: false, needsResume: false, error: null };
    element.volume = volume;
    this.handlers = {
      playing: () => { this.state.playing = true; this.state.waiting = false;
        this.state.needsResume = false; this.loading = false; this.emit(); },
      pause: () => { this.state.playing = false;
        if (this.expected() && this.strict() && !this.loading && !this.preflight && !this.holdingBoundary &&
            this.queueElapsed() < this.plan.totalSeconds - .1) {
          this.state.needsResume = true; this.interrupt('音频意外暂停，连续播放已中断。');
        }
        this.persist(true); this.emit(); },
      waiting: () => { this.state.waiting = true; this.emit(); },
      stalled: () => { this.state.waiting = true; this.emit(); },
      timeupdate: () => this.tick(),
      ended: () => this.boundary(),
      error: () => { this.state.error = '音频加载失败，请重试播放。';
        if (this.expected() && this.strict()) this.interrupt('音频加载失败。'); this.emit(); },
      loadedmetadata: () => { this.positionElement();
        if (this.expected() && !this.userPaused) void this.requestPlay(); },
    };
    for (const [event, handler] of Object.entries(this.handlers)) element.addEventListener(event, handler);
    if (autoTick) this.timer = setInterval(() => this.tick(), 100);
  }
  snapshot(): AudioControllerState { return { ...this.state }; }
  private strict(): boolean { return this.attempt?.mode === 'exam'; }
  private playingPhase(): boolean {
    const attempt = this.attempt;
    return attempt?.timing.phase === 'listening' ||
      (attempt?.timing.phase === 'practice' && (attempt.scope === 'part' || attempt.scope === 'custom'));
  }
  private queueElapsed(): number {
    const running = this.attempt?.status === 'running' && this.playingPhase();
    return this.anchor.elapsed / 1000 + (running ? Math.max(0, this.now() - this.anchor.at) / 1000 : 0);
  }
  private expected(): boolean {
    return this.allowed && this.attempt?.status === 'running' && this.plan.segments.length > 0 &&
      (!this.strict() || (this.playingPhase() && this.queueElapsed() < this.plan.totalSeconds));
  }
  update(attempt: Attempt, allowed: boolean): void {
    const changed = attempt.id !== this.id;
    const previous = this.attempt;
    const wasAllowed = this.allowed;
    this.attempt = attempt; this.allowed = allowed;
    if (changed) {
      this.generation++; this.id = attempt.id;
      this.element.pause(); this.source = ''; this.selectedIndex = -1; this.loading = false; this.playRequest = null;
      this.plan = buildQueuePlan(attempt.audio_queue);
      const saved = attempt.media_state;
      this.state.queueIndex = clamp(saved?.queue_index ?? 0, 0, Math.max(0, this.plan.segments.length - 1));
      this.state.positionSeconds = saved?.position_seconds ?? 0;
      this.state.playbackRate = saved?.playback_rate ?? 1;
      this.state.authorized = false; this.state.playing = false; this.state.error = null;
      this.state.needsResume = false; this.state.waiting = false; this.state.stalled = false;
      this.userPaused = false; this.interrupted = false;
      this.replayOnly = false;
      this.progressAt = this.now(); this.persistedAt = -Infinity;
    }
    if (changed || attempt.audio_elapsed_ms !== previous?.audio_elapsed_ms || attempt.status !== previous?.status) {
      this.anchor = { elapsed: attempt.audio_elapsed_ms, at: this.now() };
    }
    if (this.strict()) this.resolveStrict();
    this.state.queueTotalSeconds = this.plan.totalSeconds;
    const segment = this.plan.segments[this.state.queueIndex];
    this.state.durationSeconds = segment?.durationSeconds ?? 0;
    this.state.positionSeconds = clamp(this.state.positionSeconds, 0, this.state.durationSeconds);
    this.selectSource();
    if (previous?.status === 'paused' && attempt.status === 'running') this.userPaused = false;
    if (!this.expected()) {
      if (!this.preflight) this.element.pause();
    } else if (changed || previous?.status !== 'running' || !wasAllowed) {
      this.progressAt = this.now();
      if ((changed || (!wasAllowed && previous?.status === 'running')) && this.strict())
        this.interrupt('重新打开听力后已恢复考试位置，连续播放无法确认。');
      if (!this.userPaused) void this.requestPlay();
    }
    this.emit();
  }
  private emit(): void {
    if (this.stopped) return;
    const snapshot = JSON.stringify(this.state);
    if (snapshot !== this.lastSnapshot) {
      this.lastSnapshot = snapshot; this.callbacks.onState(this.snapshot());
    }
  }
  private interrupt(reason: string): void {
    if (this.interrupted || !this.strict() || !this.expected()) return;
    this.interrupted = true; this.state.stalled = true;
    this.callbacks.onInterrupt(reason, this.id);
  }
  private resolveStrict(): void {
    const resolved = resolveQueuePosition(this.plan, this.queueElapsed());
    if (resolved) {
      this.state.queueIndex = resolved.plan.index;
      this.state.positionSeconds = resolved.offsetSeconds;
      this.state.durationSeconds = resolved.plan.durationSeconds;
      this.state.playbackRate = 1;
    }
  }
  private selectSource(): void {
    const segment = this.plan.segments[this.state.queueIndex];
    if (!segment) return;
    const changedClip = this.selectedIndex !== this.state.queueIndex;
    this.selectedIndex = this.state.queueIndex;
    let changedSource = false;
    if (this.source !== segment.segment.url) {
      changedSource = true;
      this.loading = true; this.source = segment.segment.url; this.generation++;
      this.playRequest = null; this.element.src = this.source; this.element.load();
      this.progressAt = this.now();
    }
    this.element.playbackRate = this.strict() ? 1 : this.state.playbackRate;
    if (changedSource || changedClip) this.positionElement();
  }
  private positionElement(): void {
    const segment = this.plan.segments[this.state.queueIndex];
    if (!segment) return;
    const position = segment.sourceStart + this.state.positionSeconds;
    try { this.element.currentTime = position; this.observedPosition = position; }
    catch { /* loadedmetadata retries the pending position */ }
  }
  private requestPlay(): Promise<boolean> {
    if (this.playRequest) return this.playRequest;
    const generation = this.generation;
    this.playRequest = this.element.play().then(() => {
      if (this.stopped || generation !== this.generation) return false;
      this.state.authorized = true; this.state.playing = true;
      this.state.needsResume = false; this.state.error = null; this.loading = false; this.emit();
      return true;
    }).catch(() => {
      if (this.stopped || generation !== this.generation) return false;
      this.state.playing = false; this.state.needsResume = true;
      this.state.error = '请点击“重新授权播放”继续，计时不会因此增加。';
      if (this.expected() && this.strict()) this.interrupt('浏览器未允许听力续播。');
      this.emit(); return false;
    }).finally(() => { if (generation === this.generation) this.playRequest = null; });
    return this.playRequest;
  }
  async unlock(): Promise<boolean> {
    if (!this.plan.segments.length) return false;
    this.preflight = true;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      const ok = await Promise.race([this.requestPlay(), new Promise<boolean>((resolve) => {
        timeout = setTimeout(() => resolve(false), 5000);
      })]);
      if (!ok) this.state.error = '播放准备未完成，尚未开始计时，请重试。';
      return ok;
    } finally {
      if (timeout) clearTimeout(timeout);
      this.element.pause(); this.preflight = false; this.positionElement(); this.state.playing = false; this.emit();
    }
  }
  async play(): Promise<boolean> {
    if (!this.expected()) return false;
    this.userPaused = false;
    if (this.strict()) { this.resolveStrict(); this.selectSource(); }
    else if (this.state.positionSeconds >= this.state.durationSeconds) {
      this.state.positionSeconds = 0; this.positionElement();
    }
    return this.requestPlay();
  }
  pause(): void {
    if (this.strict()) return;
    this.generation++; this.playRequest = null;
    this.userPaused = true; this.element.pause(); this.state.playing = false; this.persist(true); this.emit();
  }
  seek(seconds: number): void {
    if (this.strict()) return;
    this.state.positionSeconds = clamp(seconds, 0, this.state.durationSeconds);
    this.positionElement(); this.persist(true); this.emit();
  }
  selectQuestion(id: string): void {
    if (this.strict()) return;
    const index = this.attempt?.audio_queue.findIndex((item) => item.question_ids.includes(id)) ?? -1;
    if (index < 0) {
      // The new question has no audio of its own. Any clip still playing
      // belongs to the previous question and must not survive the switch.
      this.stopCurrentClip();
      return;
    }
    if (index === this.state.queueIndex) return;
    this.replayOnly = false;
    this.state.queueIndex = index; this.state.positionSeconds = 0;
    this.state.durationSeconds = this.plan.segments[index].durationSeconds;
    this.selectSource(); this.persist(true);
    if (this.expected() && !this.userPaused) void this.requestPlay();
    this.emit();
  }
  /** Silence the current clip without touching the queue position. */
  private stopCurrentClip(): void {
    if (this.element.paused) return;
    this.generation++; this.playRequest = null;
    this.element.pause(); this.state.playing = false; this.emit();
  }
  async replayQuestion(id: string): Promise<boolean> {
    if (this.strict() || !this.expected()) return false;
    const index = this.attempt?.audio_queue.findIndex((item) => item.question_ids.includes(id)) ?? -1;
    if (index < 0) return false;
    const group = this.attempt?.groups?.find((item) => item.question_ids.includes(id));
    const clip = this.attempt!.audio_queue[index];
    if (group && (clip.question_ids.length !== group.question_ids.length ||
        !clip.question_ids.every((qid) => group.question_ids.includes(qid)))) return false;
    this.replayOnly = true; this.userPaused = false;
    this.state.queueIndex = index; this.state.positionSeconds = 0;
    this.state.durationSeconds = this.plan.segments[index].durationSeconds;
    this.selectSource(); this.positionElement(); this.persist(true); this.emit();
    return this.requestPlay();
  }
  async playSentence(sourceTime: number): Promise<boolean> {
    if (this.strict() || !this.expected() || !Number.isFinite(sourceTime)) return false;
    const clip = this.plan.segments[this.state.queueIndex];
    if (!clip || sourceTime < clip.sourceStart || sourceTime >= clip.segment.end_seconds) return false;
    this.replayOnly = true; this.userPaused = false;
    this.seek(sourceTime - clip.sourceStart);
    return this.requestPlay();
  }
  setRate(rate: number): void {
    if (this.strict()) return;
    this.state.playbackRate = clamp(rate, .5, 2); this.element.playbackRate = this.state.playbackRate;
    this.persist(true); this.emit();
  }
  setVolume(volume: number): void {
    this.state.volume = clamp(volume, 0, 1); this.element.volume = this.state.volume; this.emit();
  }
  toggleMuted(): void { this.state.muted = !this.state.muted; this.element.muted = this.state.muted; this.emit(); }
  private persist(force = false): void {
    if (this.strict() || !this.attempt || !['running', 'paused'].includes(this.attempt.status) || !this.allowed) return;
    if (!force && this.now() - this.persistedAt < 1000) return;
    this.persistedAt = this.now();
    const attemptId = this.id;
    const state = { queue_index: this.state.queueIndex,
      position_seconds: this.state.positionSeconds, playback_rate: this.state.playbackRate };
    mediaPersistence.enqueue(attemptId, {
      send: () => this.callbacks.onPersist(state, attemptId),
      failed: () => {
        if (!this.stopped && attemptId === this.id) {
          this.state.error = '音频进度暂未保存，恢复连接后会重试。'; this.emit();
        }
      },
    });
  }
  private boundary(): void {
    if (this.strict()) return;
    const next = this.state.queueIndex + 1;
    if (!this.replayOnly && next < this.plan.segments.length) {
      this.state.queueIndex = next; this.state.positionSeconds = 0;
      this.state.durationSeconds = this.plan.segments[next].durationSeconds;
      this.selectSource(); this.persist(true);
      if (this.expected() && !this.userPaused) void this.requestPlay();
    } else {
      this.state.positionSeconds = this.state.durationSeconds;
      this.element.pause(); this.positionElement(); this.state.playing = false; this.userPaused = true;
      this.persist(true);
    }
    this.emit();
  }
  tick(): void {
    if (this.stopped || this.preflight || !this.attempt) return;
    const position = this.element.currentTime;
    if (!this.element.paused && !this.element.seeking && !this.state.waiting &&
        this.element.readyState >= 3 && position > this.observedPosition + .02) {
      this.progressAt = this.now(); this.state.stalled = false;
    }
    this.observedPosition = position;
    if (this.strict()) {
      const index = this.state.queueIndex;
      this.resolveStrict();
      if (index !== this.state.queueIndex) {
        this.holdingBoundary = false;
        this.selectSource(); if (this.expected()) void this.requestPlay();
      } else {
        const entry = this.plan.segments[index];
        const desired = (entry?.sourceStart ?? 0) + this.state.positionSeconds;
        if (entry && position >= entry.segment.end_seconds && this.expected()) {
          this.holdingBoundary = true; this.element.pause(); this.positionElement();
        } else if (Math.abs(position - desired) > .6) {
          if (!this.loading && this.expected() && Math.abs(position - desired) > 1.5)
            this.interrupt('音频与考试进度不一致，已恢复到考试时间对应位置。');
          this.positionElement();
        }
      }
      if (!this.expected()) this.element.pause();
      else if (this.now() - this.progressAt >= STALL_THRESHOLD_MS) {
        this.state.needsResume = this.element.paused;
        this.interrupt(this.state.waiting ? '听力缓冲期间没有播放进度。' : '听力播放进度中断。');
      }
    } else {
      const entry = this.plan.segments[this.state.queueIndex];
      if (entry) {
        this.state.positionSeconds = clamp(position - entry.sourceStart, 0, entry.durationSeconds);
        if (this.expected() && !this.element.paused && position >= entry.segment.end_seconds - .01 && !this.userPaused) this.boundary();
        else this.persist();
      }
    }
    this.emit();
  }
  destroy(): void {
    this.persist(true);
    this.stopped = true; this.generation++;
    if (this.timer) clearInterval(this.timer);
    for (const [event, handler] of Object.entries(this.handlers)) this.element.removeEventListener(event, handler);
    this.element.pause();
  }
  leave(): void {
    if (this.expected() && this.strict()) this.interrupt('离开了听力页面，连续播放已中断。');
  }
}

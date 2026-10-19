import { PART_LABEL, formatClock } from '../../domain/format';
import type { AudioQueueItem } from '../../domain/types';
import { Tag } from '../components';
import { REVIEW_RATES, useReviewAudio } from './reviewAudio';
import type { ReactNode } from 'react';

/**
 * Review-mode replay for a graded attempt. Free play, seek, speed and segment
 * choice: grading is finished, so nothing here can affect a score.
 */
export function ReviewAudioBar({
  queue,
  focusQuestionId,
  label = '原音重听',
  replayLabel = '从头重放',
  renderTranscript,
}: {
  queue: AudioQueueItem[];
  focusQuestionId?: string;
  label?: string;
  replayLabel?: string;
  renderTranscript?: (audio: ReturnType<typeof useReviewAudio>, current: AudioQueueItem | undefined) => ReactNode;
}) {
  const initialIndex = Math.max(
    0,
    queue.findIndex((item) => focusQuestionId && item.question_ids.includes(focusQuestionId)),
  );
  const audio = useReviewAudio(queue, initialIndex);
  const { state } = audio;

  if (queue.length === 0) return null;
  const current = queue[state.index];

  return (
    <><section className="audio-bar review-audio" aria-label="复盘音频" data-testid="review-audio">
      <audio ref={audio.elementRef} preload="none" data-testid="review-audio-element" />
      <div className="audio-head">
        <div>
          <strong>{label}</strong>
          <span>
            片段 {state.index + 1} / {queue.length}
            {current
              ? ` · ${current.part === 0 ? '完整音轨' : (PART_LABEL[current.part] ?? `Part ${current.part}`)}`
              : ''}
          </span>
        </div>
        <div className="audio-state">
          {state.loading ? <Tag tone="warn">缓冲中</Tag> : null}
          <Tag tone="info">复盘：可自由控制</Tag>
        </div>
      </div>
      {state.error ? <p className="audio-error">{state.error}</p> : null}
      <div className="audio-controls">
        <button type="button" className="btn btn-secondary" onClick={() => void audio.replay()}
          data-testid="review-audio-replay">{replayLabel}</button>
        <button type="button" className="btn btn-secondary" onClick={() => audio.skip(-10)}
          data-testid="review-audio-backward">快退 10 秒</button>
        {queue.length > 1 ? <button
          type="button"
          className="btn btn-secondary"
          onClick={audio.previous}
          disabled={state.index === 0}
          aria-label="上一段"
        >
          上一段
        </button> : null}
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => (state.playing ? audio.pause() : void audio.play())}
          data-testid="review-audio-play"
        >
          {state.playing ? '暂停' : '播放'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => audio.skip(10)}
          data-testid="review-audio-forward">快进 10 秒</button>
        {queue.length > 1 ? <button
          type="button"
          className="btn btn-secondary"
          onClick={audio.next}
          disabled={state.index >= queue.length - 1}
          aria-label="下一段"
        >
          下一段
        </button> : null}
        <label className="seek">
          <span className="sr-only">复盘音频进度</span>
          <input
            type="range"
            min={0}
            max={Math.max(0.01, state.durationSeconds)}
            step={0.01}
            value={state.positionSeconds}
            onChange={(event) => audio.seek(Number(event.target.value))}
            data-testid="review-audio-seek"
          />
        </label>
        <span className="volume-value">
          {formatClock(state.positionSeconds)} / {formatClock(state.durationSeconds)}
        </span>
        <label className="rate">
          <span>倍速</span>
          <select
            value={state.rate}
            onChange={(event) => audio.setRate(Number(event.target.value))}
            data-testid="review-audio-rate"
          >
            {REVIEW_RATES.map((rate) => (
              <option key={rate} value={rate}>
                {rate}×
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="audio-volume">
        <button type="button" className="btn btn-ghost" onClick={audio.toggleMuted}
          aria-pressed={state.muted} data-testid="review-audio-mute">{state.muted ? '取消静音' : '静音'}</button>
        <label className="volume"><span className="sr-only">复盘音量</span>
          <input type="range" min={0} max={1} step={0.05} value={state.volume}
            onChange={(event) => audio.setVolume(Number(event.target.value))} data-testid="review-audio-volume" />
        </label>
      </div>
      {queue.length > 1 ? (
        <div className="review-segment-list" role="group" aria-label="选择片段">
          {queue.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className="chip chip-compact"
              data-active={index === state.index}
              onClick={() => audio.toggle(index)}
              data-testid={`review-segment-${index}`}
              title={`第 ${index + 1} 段`}
            >
              {index + 1}
            </button>
          ))}
        </div>
      ) : null}
      <p className="audio-note">复盘可自由控制；本段结束后停止，不影响本次成绩。</p>
    </section>{renderTranscript?.(audio, current)}</>
  );
}

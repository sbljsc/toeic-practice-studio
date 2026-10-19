import { useEffect, useMemo, useRef, useState } from 'react';
import type { AudioQueueItem, ListeningScript } from '../domain/types';
import { formatClock } from '../domain/format';
import { activeSentenceId, followScrollTop, selectionTouchesSentence, validSentences } from './subtitleSync';
import { MarkdownText, MarkdownInline } from './MaterialContent';

export function TranscriptPanel({ script, clip, sourceTime, onSentence, disabled = false }: {
  script: ListeningScript;
  clip?: AudioQueueItem;
  sourceTime?: number;
  onSentence?: (sourceTime: number) => void;
  disabled?: boolean;
}) {
  const [showChinese, setShowChinese] = useState(false);
  const [following, setFollowing] = useState(true);
  const pane = useRef<HTMLOListElement | null>(null);
  const rows = useRef(new Map<string, HTMLButtonElement>());
  const sentences = useMemo(() => validSentences(script, clip), [script, clip]);
  const activeId = activeSentenceId(sentences, sourceTime ?? NaN);
  const panelId = `translation-${clip?.id ?? 'script'}`;

  useEffect(() => {
    if (!following || !activeId) return;
    const container = pane.current, row = rows.current.get(activeId);
    if (!container || !row) return;
    const target = followScrollTop({ scrollTop: container.scrollTop, viewportHeight: container.clientHeight,
      scrollHeight: container.scrollHeight, rowTop: row.offsetTop, rowHeight: row.offsetHeight });
    if (target !== null) container.scrollTo({ top: target,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }, [activeId, following, showChinese]);

  return (
    <div className="listening-script" data-testid="listening-script">
      <div className="script-head">
        <h4>英文字幕</h4>
        <div className="script-actions">
          {sentences.length > 0 ? (
            <button type="button" className="btn btn-ghost" aria-pressed={following}
              onClick={() => setFollowing((value) => !value)} data-testid="subtitle-follow">
              {following ? '正在跟随' : '跟随播放'}
            </button>
          ) : null}
          <button type="button" className="btn btn-secondary" aria-expanded={showChinese}
            aria-controls={panelId} disabled={!script.chinese}
            onClick={() => setShowChinese((value) => !value)} data-testid="toggle-chinese">
            {showChinese ? '隐藏中文对照' : '显示中文对照'}
          </button>
        </div>
      </div>
      {sentences.length > 0 ? <p className="audio-note">点击英文句子从这里播放；滚动字幕可暂停跟随。</p> : null}
      <div className="script-columns" data-bilingual={showChinese}>
        <div className="script-english" lang="en" data-testid="english-subtitles">
          {sentences.length > 0 ? (
            <ol className="subtitle-lines" aria-label="逐句英文字幕" ref={pane}
              onWheel={() => setFollowing(false)} onTouchMove={() => setFollowing(false)}
              data-testid="subtitle-lines">
              {sentences.map((sentence, index) => (
                <li key={sentence.id}>
                  <button type="button" className="subtitle-sentence" data-active={activeId === sentence.id}
                    aria-current={activeId === sentence.id ? 'true' : undefined}
                    disabled={disabled || !onSentence}
                    ref={(row) => { if (row) rows.current.set(sentence.id, row); else rows.current.delete(sentence.id); }}
                    onClick={(event) => {
                      const selection = window.getSelection();
                      if (selectionTouchesSentence(selection, event.currentTarget)) return;
                      setFollowing(true); onSentence?.(sentence.start_seconds);
                    }}
                    data-testid={`subtitle-sentence-${index}`} data-sentence-id={sentence.id}
                    data-start={sentence.start_seconds} data-end={sentence.end_seconds}
                    title="从本句开始播放">
                    <span className="subtitle-time" aria-hidden="true">{formatClock(sentence.start_seconds - (clip?.start_seconds ?? 0))}</span>
                    <MarkdownInline className="subtitle-text" text={sentence.text} />
                  </button>
                </li>
              ))}
            </ol>
          ) : <MarkdownText text={script.english} />}
        </div>
        {showChinese ? (
          <div className="script-chinese" lang="zh-CN" id={panelId} data-testid="chinese-subtitles">
            <h5>中文对照</h5><MarkdownText text={script.chinese} />
          </div>
        ) : null}
      </div>
      {!script.chinese ? <p className="audio-note">这段材料暂缺可核对的中文译文。</p> : null}
    </div>
  );
}

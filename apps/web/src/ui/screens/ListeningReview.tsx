import type { ReportGroup } from '../../domain/types';
import { TranscriptPanel } from '../TranscriptPanel';
import { ReviewAudioBar } from './ReviewAudioBar';

export function ListeningReview({ group }: { group: ReportGroup }) {
  const shared = group.question_ids.length > 1;
  const script = group.listening_script;
  return (
    <section className="listening-review" aria-label="听力原文与重放" data-testid="listening-review">
      {group.review_audio ? (
        <ReviewAudioBar queue={[group.review_audio]}
          label={shared ? '本篇听力' : '本题听力'} replayLabel={shared ? '重放本篇' : '重放本题'}
          renderTranscript={(audio, clip) => script?.english ? (
            <TranscriptPanel key={group.id} script={script} clip={clip}
              sourceTime={(clip?.start_seconds ?? 0) + audio.state.positionSeconds}
              onSentence={(sourceTime) => void audio.playSentence(sourceTime)} />
          ) : <p className="audio-note">这条记录暂缺可核对的英文字幕。</p>} />
      ) : (
        <>
          <p className="audio-note">这条历史记录未保存单题音频区间。</p>
          {script?.english ? <TranscriptPanel key={group.id} script={script} /> : null}
        </>
      )}
    </section>
  );
}

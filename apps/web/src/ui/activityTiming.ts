import type { ActivitySummary } from '../domain/types';
export interface TimePoint { key: string; label: string; dwell: number | null; first: number | null }
export function timingPoints(activity: ActivitySummary | undefined, mode: 'question' | 'part'): TimePoint[] {
  if (!activity || activity.coverage === 'unavailable') return [];
  const clean = (value: number | null) => value !== null && Number.isFinite(value) && value >= 0 ? value : null;
  return mode === 'question' ? activity.questions.map((q, i) => ({ key: q.question_id,
    label: `第 ${i + 1} 题 · Part ${q.part}`, dwell: clean(q.dwell_ms), first: clean(q.first_answer_ms) })) :
    activity.parts.map((p) => ({ key: String(p.part), label: `Part ${p.part}`, dwell: clean(p.dwell_ms), first: null }));
}
export function timingSegments(points: TimePoint[], width = 800, height = 200): string[] {
  const max = Math.max(1, ...points.map((p) => p.dwell ?? 0));
  const segments: string[] = [];
  let segment: string[] = [];
  points.forEach((point, index) => {
    if (point.dwell === null) { if (segment.length) segments.push(segment.join(' ')); segment = []; return; }
    segment.push(`${40 + index * (width - 60) / Math.max(1, points.length - 1)},${height - 30 - point.dwell / max * (height - 60)}`);
  });
  if (segment.length) segments.push(segment.join(' '));
  return segments;
}
export function elapsedText(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '未记录';
  return `${(ms / 1000).toFixed(1)} 秒`;
}

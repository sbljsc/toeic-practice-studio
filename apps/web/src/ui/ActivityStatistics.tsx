import { useId, useState } from 'react';
import type { ActivitySummary } from '../domain/types';
import { elapsedText, timingPoints, timingSegments } from './activityTiming';

export function ActivityStatistics({ activity, live = false }: { activity?: ActivitySummary; live?: boolean }) {
  const [mode, setMode] = useState<'question' | 'part'>('question');
  const id = useId();
  const points = timingPoints(activity, mode);
  const available = !!activity && activity.coverage !== 'unavailable';
  const max = Math.max(1, ...points.map((p) => p.dwell ?? 0));
  return <section className="activity-statistics" aria-label="作答用时统计" data-testid="activity-statistics">
    <div className="section-head"><h2>作答用时</h2><div className="chip-row" role="group" aria-label="用时维度">
      <button type="button" className="chip" aria-pressed={mode === 'question'} data-active={mode === 'question'} onClick={() => setMode('question')}>逐题</button>
      <button type="button" className="chip" aria-pressed={mode === 'part'} data-active={mode === 'part'} onClick={() => setMode('part')}>Part</button>
    </div></div>
    <p className="page-sub">{live ? '计时与音频继续运行；此处不显示答案或成绩。' : '用时在交卷时冻结，复盘不会修改记录。'} 仅按已收到的前台停留记录；网络异常时可能漏记或多记，考试计时不受影响。共用材料阅读计入当前题，建议结合 Part 用时观察。</p>
    {!available ? <p className="answer-empty">这条历史记录没有逐题用时数据，无法绘制曲线。没有根据总时长推算。</p> : <>
      {activity.coverage === 'partial' && <p className="phase-note">本轮为部分记录，开始记录前的时间没有逐题数据。</p>}
      <dl className="timing-totals"><div><dt>总作答时间</dt><dd>{elapsedText(activity.total_elapsed_ms)}</dd></div><div><dt>已归属题目</dt><dd>{elapsedText(activity.tracked_ms)}</dd></div><div><dt>未归属时间</dt><dd>{elapsedText(activity.unattributed_ms)}</dd></div></dl>
      <svg className="time-chart" viewBox="0 0 800 200" role="img" aria-labelledby={`${id}-title ${id}-desc`}>
        <title id={`${id}-title`}>{mode === 'question' ? '逐题' : 'Part'}停留用时曲线</title>
        <desc id={`${id}-desc`}>横轴为本轮题序或 Part，纵轴为秒。缺失值断开；完整数值见下方表格。</desc>
        <path d="M40 20V170H780" fill="none" stroke="currentColor" opacity=".3" />
        <text x="4" y="25">{Math.ceil(max / 1000)}s</text><text x="12" y="172">0</text>
        {timingSegments(points).map((segment, i) => <polyline key={i} points={segment} fill="none" stroke="var(--accent)" strokeWidth="2" />)}
        {points.map((point, i) => point.dwell === null ? null : <circle key={point.key} cx={40 + i * 740 / Math.max(1, points.length - 1)} cy={170 - point.dwell / max * 140} r="3" fill="var(--accent)"><title>{point.label}：{elapsedText(point.dwell)}</title></circle>)}
        <text x="40" y="195">{mode === 'question' ? '第 1 题' : points[0]?.label}</text><text x="780" y="195" textAnchor="end">{mode === 'question' ? `第 ${points.length} 题` : points.at(-1)?.label}</text>
      </svg>
      <div className="timing-table"><table><caption>{mode === 'question' ? '逐题' : 'Part'}用时明细（缺失值不连接、不推算）</caption><thead><tr><th scope="col">{mode === 'question' ? '本轮题序' : 'Part'}</th><th scope="col">停留用时</th>{mode === 'question' && <th scope="col">首次作答前停留</th>}</tr></thead><tbody>
        {points.map((point) => <tr key={point.key}><th scope="row">{point.label}</th><td>{elapsedText(point.dwell)}</td>{mode === 'question' && <td>{elapsedText(point.first)}</td>}</tr>)}
      </tbody></table></div>
      <p className="page-sub">首次作答用时指服务端首次接受非空答案前已记录的停留时间。正常收到切换事件后，后台、统计页与暂停时间不归属题目；未记录的时间不推算。</p>
    </>}
  </section>;
}

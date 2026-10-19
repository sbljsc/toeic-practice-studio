import { useEffect, useRef, useState } from 'react';
import type { ActivitySummary, Attempt } from '../../domain/types';
import { api } from '../../domain/http';
import { ActivityChannel } from './activityChannel';
import { activityTarget } from './workspaceNavigation';

export function useActivity(attempt: Attempt | null, index: number, answering: boolean, owner: boolean) {
  const [record, setRecord] = useState<{ attemptId: string; activity: ActivitySummary }>();
  const mounted = useRef(true);
  const [notice, setNotice] = useState<string | null>(null);
  const context = useRef({ attempt, index, answering, owner });
  context.current = { attempt, index, answering, owner };
  const channel = useRef<ActivityChannel | null>(null);
  if (!channel.current) channel.current = new ActivityChannel(async (event) => {
    const current = context.current;
    if (!current.attempt || !current.owner || current.attempt.activity_session_id !== event.session_id) return;
    const id = current.attempt.id;
    try {
      const response = await api.activity(id, event);
      const latest = context.current;
      if (mounted.current && latest.attempt?.id === id && latest.attempt.activity_session_id === event.session_id && latest.owner) {
        setRecord({ attemptId: id, activity: response.activity }); setNotice(null);
      }
    } catch {
      if (mounted.current && context.current.owner && context.current.attempt?.id === id && context.current.attempt.activity_session_id === event.session_id) setNotice('逐题用时暂未同步；网络异常期间的停留记录可能不完整，考试计时不受影响。');
    }
  });
  useEffect(() => { setRecord(undefined); setNotice(null); }, [attempt?.id]);
  useEffect(() => {
    const update = () => {
      const { attempt: current, index: at, answering: answerView, owner: owns } = context.current;
      const session = owns && current && !['submitted', 'expired'].includes(current.status) ? current.activity_session_id ?? null : null;
      channel.current!.select(session, current ? activityTarget(current, at, answerView, document.visibilityState === 'visible', owns) : null);
    };
    update();
    const heartbeat = setInterval(update, 5000);
    document.addEventListener('visibilitychange', update);
    const leaving = () => channel.current!.select(context.current.owner ? context.current.attempt?.activity_session_id ?? null : null, null);
    window.addEventListener('pagehide', leaving);
    return () => { clearInterval(heartbeat); document.removeEventListener('visibilitychange', update); window.removeEventListener('pagehide', leaving); };
  }, [attempt?.id, attempt?.activity_session_id, attempt?.status, attempt?.timing.phase, attempt?.timing.is_paused, attempt?.timing.phase_question_ids, index, answering, owner]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const current = context.current;
      if (current.owner) channel.current!.select(current.attempt?.activity_session_id ?? null, null);
    };
  }, []);
  return { activity: record?.attemptId === attempt?.id ? record?.activity ?? attempt?.activity : attempt?.activity, notice };
}

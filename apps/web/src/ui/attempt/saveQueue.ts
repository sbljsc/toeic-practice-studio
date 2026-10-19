import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import { getTabId } from '../../domain/tab';
import { deleteDraft, listDrafts, saveDraft, type PendingDraft } from '../../domain/drafts';
import { newMutationId } from '../../domain/format';
import type { AnswerState, Attempt } from '../../domain/types';
import { AnswerWriteQueue, summarizeFlush, type AnswerValue, type QueuedWrite,
  type FlushOutcome, type SendResult } from './answerQueue';
import { acknowledgeChoice, type LocalAnswer } from './answerState';
export type { LocalAnswer } from './answerState';
export type SaveState = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict' | 'readonly' | 'expired';
export interface ConflictPrompt { questionId: string; server: AnswerState; draft: AnswerState }
interface Options {
  attempt: Attempt;
  readOnly: boolean;
  onAttempt: (next: Attempt) => void;
  onBanner: (message: string | null) => void;
  onOwnershipLost?: () => void;
  ownershipEpoch?: () => number;
}
type Desired = { write: QueuedWrite; createdAt: number };
const isClosed = (attempt: Attempt) => ['submitted', 'expired'].includes(attempt.status);

function hydrate(attempt: Attempt): Record<string, LocalAnswer> {
  return Object.fromEntries(attempt.questions.map((question) => [question.id, {
    ...(attempt.answers[question.id] ?? { option_id: null, flagged: false, visited: false, revision: 0 }),
    dirty: false,
  }]));
}
export function useAnswerPipeline(options: Options) {
  const { attempt, readOnly } = options;
  const context = useRef(options); context.current = options;
  const tabId = useMemo(getTabId, []);
  const [answers, setAnswers] = useState<Record<string, LocalAnswer>>(() => hydrate(attempt));
  const answersRef = useRef(answers);
  const publish = useCallback((next: Record<string, LocalAnswer>) => {
    answersRef.current = next; setAnswers(next);
  }, []);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [conflict, setConflict] = useState<ConflictPrompt | null>(null);
  const [unscoredDrafts, setUnscoredDrafts] = useState<PendingDraft[]>([]);
  const queue = useMemo(() => new AnswerWriteQueue(), []);
  const desired = useRef(new Map<string, Desired>());
  const conflicts = useRef(new Map<string, ConflictPrompt>());
  const errors = useRef(new Map<string, string>());
  const blocked = useRef(new Set<string>());
  const frozen = useRef(false);
  const localStorageWorks = useRef(true);
  const lastStamp = useRef(Date.now());
  const retryRef = useRef<() => Promise<void>>(async () => undefined);
  const recoveryReady = useRef(false);
  const recoveryPromise = useRef<Promise<void> | null>(null);
  const deferredMetadata = useRef(new Map<string, Partial<LocalAnswer>>());

  const updateStatus = useCallback(() => {
    const current = context.current;
    setConflict(conflicts.current.values().next().value ?? null);
    if (current.readOnly) setSaveState('readonly');
    else if (conflicts.current.size) setSaveState('conflict');
    else if (errors.current.size || blocked.current.size) setSaveState('failed');
    else if (queue.pendingQuestionIds().length) setSaveState('saving');
    else setSaveState('saved');
    const problem = errors.current.values().next().value;
    current.onBanner(problem ?? null);
  }, [queue]);

  const persist = useCallback(async (id: string, write: QueuedWrite, attemptId: string) => {
    const latest = desired.current.get(id);
    if (!latest || latest.write.sequence !== write.sequence) return;
    try {
      await saveDraft({ attemptId, questionId: id, tabId, mutationId: write.mutationId,
        expectedRevision: write.value.revision, optionId: write.value.option_id,
        flagged: write.value.flagged, visited: write.value.visited,
        createdAt: latest.createdAt, lastError: '' });
    } catch {
      localStorageWorks.current = false;
      context.current.onBanner('本机草稿无法保存。未确认的选择暂留在当前页面，请保持页面打开并重试。');
    }
  }, [tabId]);

  const send = useCallback(async (id: string, value: AnswerValue, mutationId: string,
    sequence = 0): Promise<SendResult> => {
    const current = context.current;
    const attemptId = current.attempt.id;
    const epoch = current.ownershipEpoch?.() ?? 0;
    const stillCurrent = () => context.current.attempt.id === attemptId &&
      (context.current.ownershipEpoch?.() ?? 0) === epoch;
    if (current.readOnly || isClosed(current.attempt) || current.attempt.status !== 'running' ||
        blocked.current.has(id) || conflicts.current.has(id)) return { ok: false, kind: 'aborted' };
    await persist(id, { value, mutationId, sequence }, attemptId);
    try {
      const next = await api.saveAnswer(attemptId, id, { ...value, mutation_id: mutationId });
      if (!stillCurrent()) return { ok: false, kind: 'aborted' };
      const actual = next.answers[id] ?? { option_id: null, flagged: false, visited: false, revision: 0 };
      if (actual.revision !== value.revision + 1 || actual.option_id !== value.option_id ||
          actual.flagged !== value.flagged || actual.visited !== value.visited) {
        // An idempotent replay returns the CURRENT attempt. A different newer
        // answer is not an acknowledgment of this old choice or its successors.
        current.onAttempt(next); errors.current.delete(id);
        conflicts.current.set(id, { questionId: id, server: actual,
          draft: { ...(answersRef.current[id] ?? value) } });
        return { ok: false, kind: 'conflict', server: actual };
      }
      const revision = actual.revision;
      const latest = desired.current.get(id);
      const hasNewer = !!latest && latest.write.sequence > sequence;
      const local = answersRef.current[id];
      if (local) publish({ ...answersRef.current,
        [id]: acknowledgeChoice(local, value, revision, hasNewer) });
      if (hasNewer && latest) {
        // This rebase follows our own ack, not a fresh unrelated server value.
        latest.write.value = { ...latest.write.value, revision };
        await persist(id, latest.write, attemptId);
      }
      errors.current.delete(id);
      current.onAttempt(next);
      return { ok: true, revision };
    } catch (error) {
      if (!stillCurrent()) return { ok: false, kind: 'aborted' };
      const cause = error instanceof ApiError ? error : null;
      if (cause?.code === 'tab_conflict' || cause?.code === 'claim_required') {
        current.onOwnershipLost?.();
        const lossEpoch = context.current.ownershipEpoch?.() ?? 0;
        try {
          const fresh = await api.getAttempt(attemptId);
          if (context.current.attempt.id === attemptId &&
              (context.current.ownershipEpoch?.() ?? 0) === lossEpoch) current.onAttempt(fresh);
        } catch { /* keep read-only */ }
        return { ok: false, kind: 'aborted' };
      }
      if (cause?.isRevisionConflict) {
        let server: AnswerState = value;
        try {
          const fresh = await api.getAttempt(attemptId);
          if (!stillCurrent()) return { ok: false, kind: 'aborted' };
          server = fresh.answers[id] ?? { option_id: null, flagged: false, visited: false, revision: 0 };
          current.onAttempt(fresh);
        } catch { /* retain the latest desired choice */ }
        if (!stillCurrent()) return { ok: false, kind: 'aborted' };
        errors.current.delete(id);
        conflicts.current.set(id, { questionId: id, server,
          draft: { ...(answersRef.current[id] ?? value) } });
        return { ok: false, kind: 'conflict', server };
      }
      if (cause?.code === 'is_paused') {
        errors.current.set(id, '练习已暂停，继续后会重试本机草稿。');
        try {
          const fresh = await api.getAttempt(attemptId);
          if (stillCurrent()) current.onAttempt(fresh);
        } catch { /* next clock sync retries */ }
        return { ok: false, kind: 'aborted' };
      }
      if (cause?.status === 410 || cause?.code === 'section_locked') {
        blocked.current.add(id);
        errors.current.set(id, cause.message + ' 这份本机草稿尚未计分。');
        return { ok: false, kind: 'aborted' };
      }
      const message = (cause?.message ?? '保存失败。') + (localStorageWorks.current
        ? ' 选择保留为本机草稿，恢复连接后重试。'
        : ' 选择只保留在当前页面，请保持页面打开后重试。');
      errors.current.set(id, message);
      return { ok: false, kind: 'error', message };
    }
  }, [persist, publish]);

  const runQueue = useCallback(async (id: string) => {
    const attemptId = context.current.attempt.id;
    const result = await queue.drain(id, send);
    if (attemptId !== context.current.attempt.id) return result.result;
    const latest = desired.current.get(id);
    if (result.result.ok && latest && !queue.isStale(id, result.sequence)) {
      queue.settle(id, result.sequence);
      // IndexedDB checks the ID atomically; a newer write cannot be deleted.
      await deleteDraft(attemptId, id, latest.write.mutationId, tabId).catch(() => undefined);
    }
    updateStatus();
    return result.result;
  }, [queue, send, tabId, updateStatus]);

  const mutate = useCallback((id: string, patch: Partial<LocalAnswer>) => {
    const current = context.current;
    if (current.readOnly || frozen.current || current.attempt.status !== 'running' ||
        conflicts.current.has(id) || blocked.current.has(id)) return;
    if (current.attempt.mode === 'exam' &&
        !current.attempt.timing.phase_question_ids.includes(id)) return;
    const base = answersRef.current[id];
    if (!base) return;
    const next = { ...base, ...patch, dirty: true };
    publish({ ...answersRef.current, [id]: next });
    const write = queue.enqueue(id, next, newMutationId());
    lastStamp.current = Math.max(Date.now(), lastStamp.current + .01);
    desired.current.set(id, { write, createdAt: lastStamp.current });
    // Persist on the click itself, including choices queued behind an in-flight write.
    void persist(id, write, current.attempt.id);
    setSaveState('saving');
    void runQueue(id);
  }, [persist, publish, queue, runQueue]);

  const mutateMetadata = useCallback((id: string, patch: Partial<LocalAnswer>) => {
    if (!recoveryReady.current) {
      const current = context.current;
      if (current.readOnly || current.attempt.status !== 'running') return;
      // Visiting/bookmarking does not express a new answer. Wait for the
      // durable answer and resolve its unknown acknowledgment before merging.
      deferredMetadata.current.set(id, { ...deferredMetadata.current.get(id), ...patch });
      return;
    }
    mutate(id, patch);
  }, [mutate]);

  useEffect(() => {
    let live = true;
    const attemptId = attempt.id;
    queue.reset(); desired.current.clear(); conflicts.current.clear();
    errors.current.clear(); blocked.current.clear();
    recoveryReady.current = false; recoveryPromise.current = null; deferredMetadata.current.clear();
    setConflict(null); setUnscoredDrafts([]);
    publish(hydrate(attempt));
    if (!attemptId) { recoveryReady.current = true; return; }
    recoveryPromise.current = listDrafts(attemptId, tabId).then(async (records) => {
      if (!live || context.current.attempt.id !== attemptId) return;
      if (isClosed(context.current.attempt)) { setUnscoredDrafts(records); return; }
      const newest = new Map<string, PendingDraft>();
      for (const draft of records) {
        const previous = newest.get(draft.questionId);
        if (!previous || previous.createdAt < draft.createdAt) newest.set(draft.questionId, draft);
        lastStamp.current = Math.max(lastStamp.current, draft.createdAt);
      }
      for (const draft of newest.values()) {
        if (!answersRef.current[draft.questionId]) continue;
        // IndexedDB may finish after a fresh click. Recovery never replaces a
        // choice explicitly made in this document while that read was pending.
        if (desired.current.has(draft.questionId)) continue;
        const value: LocalAnswer = { option_id: draft.optionId, flagged: draft.flagged,
          visited: draft.visited, revision: draft.expectedRevision, dirty: true };
        const write = queue.enqueue(draft.questionId, value, draft.mutationId);
        desired.current.set(draft.questionId, { write, createdAt: draft.createdAt });
        publish({ ...answersRef.current, [draft.questionId]: value });
        if (!draft.tabId) {
          await persist(draft.questionId, write, attemptId);
          if (localStorageWorks.current)
            await deleteDraft(attemptId, draft.questionId, draft.mutationId).catch(() => undefined);
        }
      }
    }).catch(() => { localStorageWorks.current = false; }).then(async () => {
      if (!live || context.current.attempt.id !== attemptId) return;
      recoveryReady.current = true;
      await retryRef.current();
      if (!live || context.current.attempt.id !== attemptId) return;
      const metadata = [...deferredMetadata.current]; deferredMetadata.current.clear();
      for (const [id, patch] of metadata) {
        if (Object.entries(patch).some(([key, value]) =>
          answersRef.current[id]?.[key as keyof LocalAnswer] !== value)) mutate(id, patch);
      }
    });
    return () => { live = false; };
    // Recovery runs once for an identity; later DTOs must not overwrite dirty choices.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt.id, persist, publish, queue, tabId, mutate]);

  useEffect(() => {
    const next = { ...answersRef.current };
    for (const [id, server] of Object.entries(attempt.answers)) {
      if (!next[id]?.dirty && server.revision >= (next[id]?.revision ?? 0))
        next[id] = { ...server, dirty: false };
    }
    publish(next);
  }, [attempt.answers, publish]);

  const retryAll = useCallback(async () => {
    const current = context.current;
    if (current.readOnly || current.attempt.status !== 'running' || frozen.current) return;
    await Promise.all(queue.pendingQuestionIds().filter((id) =>
      !conflicts.current.has(id) && !blocked.current.has(id)).map(runQueue));
    updateStatus();
  }, [queue, runQueue, updateStatus]);
  retryRef.current = retryAll;
  const previousMode = useRef(attempt.mode);
  useEffect(() => {
    if (previousMode.current === 'exam' && attempt.mode === 'practice') {
      // A deliberate conversion removes the old section lock; its durable
      // drafts can now be retried under practice rules after resuming.
      for (const id of blocked.current) errors.current.delete(id);
      blocked.current.clear(); updateStatus(); void retryRef.current();
    }
    previousMode.current = attempt.mode;
  }, [attempt.mode, updateStatus]);
  useEffect(() => {
    if (!readOnly && attempt.status === 'running') void retryAll();
    const reconnect = () => void retryAll();
    const retry = window.setInterval(() => {
      if (queue.pendingQuestionIds().length) void retryAll();
    }, 3000);
    window.addEventListener('online', reconnect);
    return () => { clearInterval(retry); window.removeEventListener('online', reconnect); };
  }, [attempt.status, readOnly, retryAll, queue]);

  const flushPending = useCallback(async (): Promise<FlushOutcome> => {
    const attemptId = context.current.attempt.id;
    await recoveryPromise.current;
    if (context.current.attempt.id !== attemptId) return { ok: false, failed: 0, aborted: 1 };
    frozen.current = true;
    try {
      const current = context.current;
      if (current.readOnly) return { ok: false, failed: 0, aborted: 1 };
      if (conflicts.current.size || blocked.current.size)
        return { ok: false, failed: conflicts.current.size + blocked.current.size, aborted: 0 };
      const ids = queue.pendingQuestionIds();
      const result = await Promise.all(ids.map(async (id) => [id, await runQueue(id)] as const));
      return summarizeFlush(new Map(result));
    } finally { frozen.current = false; }
  }, [queue, runQueue]);

  const resolveConflict = useCallback((choice: 'server' | 'local') => {
    const item = conflicts.current.values().next().value;
    if (!item) return;
    const id = item.questionId, old = desired.current.get(id);
    conflicts.current.delete(id); errors.current.delete(id); queue.reset(id);
    if (choice === 'server') {
      publish({ ...answersRef.current, [id]: { ...item.server, dirty: false } });
      if (old) void deleteDraft(context.current.attempt.id, id, old.write.mutationId, tabId);
      desired.current.delete(id);
    } else {
      const value = { ...item.draft, revision: item.server.revision, dirty: true };
      publish({ ...answersRef.current, [id]: value });
      const write = queue.enqueue(id, value, newMutationId());
      lastStamp.current = Math.max(Date.now(), lastStamp.current + .01);
      desired.current.set(id, { write, createdAt: lastStamp.current });
      void persist(id, write, context.current.attempt.id);
      void runQueue(id);
    }
    updateStatus();
  }, [persist, publish, queue, runQueue, tabId, updateStatus]);

  return { answers, saveState, conflict, unscoredDrafts, retryAll, flushPending, resolveConflict,
    selectOption: (id: string, option: 'A' | 'B' | 'C' | 'D') => mutate(id, { option_id: option, visited: true }),
    clearOption: (id: string) => mutate(id, { option_id: null, visited: true }),
    toggleFlag: (id: string) => mutateMetadata(id, {
      flagged: !(deferredMetadata.current.get(id)?.flagged ?? answersRef.current[id]?.flagged) }),
    markVisited: (id: string) => { if (!answersRef.current[id]?.visited) mutateMetadata(id, { visited: true }); },
    dismissUnscored: () => setUnscoredDrafts([]) };
}

export interface AnswerValue {
  option_id: 'A' | 'B' | 'C' | 'D' | null;
  flagged: boolean;
  visited: boolean;
  revision: number;
}
export interface QueuedWrite { value: AnswerValue; mutationId: string; sequence: number }
export type SendResult =
  | { ok: true; revision: number }
  | { ok: false; kind: 'conflict'; server: AnswerValue }
  | { ok: false; kind: 'error'; message: string }
  | { ok: false; kind: 'aborted' };
export type SendFn = (questionId: string, value: AnswerValue, mutationId: string,
                      sequence?: number) => Promise<SendResult>;
export interface DrainResult { result: SendResult; sequence: number | null }
export interface FlushOutcome { ok: boolean; failed: number; aborted: number }
interface Entry {
  pending: QueuedWrite | null;
  sending: QueuedWrite | null;
  retry: QueuedWrite | null;
  running: Promise<DrainResult> | null;
  acknowledgedRevision: number | undefined;
  latestSequence: number;
  last: DrainResult;
  cancelled: boolean;
}
/** Failed/unknown acknowledgments are resolved before dependent writes.
 * Recovered drafts retain their recorded revision. Only our own successful
 * acknowledgment can rebase the next write in this ownership chain. */
export class AnswerWriteQueue {
  private readonly entries = new Map<string, Entry>();
  private sequence = 0;
  private entryFor(id: string): Entry {
    let entry = this.entries.get(id);
    if (!entry) {
      entry = { pending: null, sending: null, retry: null, running: null,
        acknowledgedRevision: undefined, latestSequence: 0, cancelled: false,
        last: { result: { ok: true, revision: 0 }, sequence: null } };
      this.entries.set(id, entry);
    }
    return entry;
  }
  enqueue(id: string, value: AnswerValue, mutationId: string): QueuedWrite {
    const entry = this.entryFor(id);
    const write = { value: { ...value, revision: entry.acknowledgedRevision ?? value.revision },
      mutationId, sequence: ++this.sequence };
    entry.latestSequence = write.sequence;
    entry.pending = write;
    return write;
  }
  latest(id: string): QueuedWrite | null {
    const entry = this.entries.get(id);
    return entry?.pending ?? entry?.retry ?? entry?.sending ?? null;
  }
  isSending(id: string): boolean { return !!this.entries.get(id)?.running; }
  hasPending(id: string): boolean {
    const entry = this.entries.get(id);
    return !!(entry?.pending || entry?.retry);
  }
  pendingQuestionIds(): string[] {
    return [...this.entries].filter(([, e]) => e.pending || e.retry || e.running).map(([id]) => id);
  }
  isStale(id: string, sequence: number | null): boolean {
    return sequence === null || (this.entries.get(id)?.latestSequence ?? 0) > sequence;
  }
  drain(id: string, send: SendFn): Promise<DrainResult> {
    const entry = this.entryFor(id);
    // Submit and retry join the current send rather than treating it as aborted.
    if (entry.running) return entry.running;
    if (!entry.retry && !entry.pending) return Promise.resolve(entry.last);
    let resolve!: (result: DrainResult) => void;
    entry.running = new Promise<DrainResult>((done) => { resolve = done; });
    const running = entry.running;
    void this.run(id, entry, send).then((result) => {
      entry.running = null;
      resolve(result);
    });
    return running;
  }
  private async run(id: string, entry: Entry, send: SendFn): Promise<DrainResult> {
    while (!entry.cancelled && (entry.retry || entry.pending)) {
      const write = entry.retry ?? entry.pending!;
      if (entry.retry) entry.retry = null;
      else entry.pending = null;
      entry.sending = write;
      let result: SendResult;
      try { result = await send(id, write.value, write.mutationId, write.sequence); }
      catch (error) { result = { ok: false, kind: 'error', message: String(error) }; }
      entry.sending = null;
      if (entry.cancelled) return { result: { ok: false, kind: 'aborted' }, sequence: write.sequence };
      entry.last = { result, sequence: write.sequence };
      if (!result.ok) {
        // The response might be lost after commit. Retry this exact ID before
        // sending a newer choice, so a network failure cannot silently lose it.
        entry.retry = write;
        return entry.last;
      }
      entry.acknowledgedRevision = result.revision;
      if (entry.pending) entry.pending.value = { ...entry.pending.value, revision: result.revision };
    }
    return entry.last;
  }
  async drainAll(send: SendFn, shouldAbort?: () => boolean): Promise<Map<string, DrainResult>> {
    return new Map(await Promise.all(this.pendingQuestionIds().map(async (id) => {
      const result: DrainResult = shouldAbort?.()
        ? { result: { ok: false, kind: 'aborted' }, sequence: null }
        : await this.drain(id, send);
      return [id, result] as const;
    })));
  }
  settle(id: string, sequence: number | null): boolean {
    const entry = this.entries.get(id);
    if (!entry || sequence === null || this.isStale(id, sequence) || entry.running || entry.retry) return false;
    entry.pending = null;
    return true;
  }
  reset(id?: string): void {
    if (id !== undefined) {
      const entry = this.entries.get(id);
      if (entry) entry.cancelled = true;
      this.entries.delete(id);
    } else {
      for (const entry of this.entries.values()) entry.cancelled = true;
      this.entries.clear();
    }
  }
}
export function summarizeFlush(results: Map<string, SendResult>): FlushOutcome {
  let failed = 0, aborted = 0;
  for (const result of results.values()) {
    if (!result.ok) { if (result.kind === 'aborted') aborted++; else failed++; }
  }
  return { ok: failed === 0 && aborted === 0, failed, aborted };
}

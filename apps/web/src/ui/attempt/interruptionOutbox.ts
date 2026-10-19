export interface PendingInterruption {
  event_id: string;
  attempt_id: string;
  reason: string;
  occurred_at_ms: number;
  owner_tab_id?: string;
}
export interface OutboxStorage {
  length: number;
  key(index: number): string | null;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}
const PREFIX = 'toeic.media-interruption.';

/** Independent keys avoid read/modify/write races between learner tabs. */
export class InterruptionOutbox {
  private storage: OutboxStorage;
  constructor(storage: OutboxStorage) { this.storage = storage; }
  add(event: PendingInterruption): void {
    this.storage.setItem(PREFIX + event.event_id, JSON.stringify(event));
  }
  pending(attemptId?: string): PendingInterruption[] {
    const result: PendingInterruption[] = [];
    const keys = Array.from({ length: this.storage.length }, (_, index) => this.storage.key(index));
    for (const key of keys) {
      if (!key?.startsWith(PREFIX)) continue;
      try {
        const event = JSON.parse(this.storage.getItem(key) ?? '') as PendingInterruption;
        if ((!attemptId || event.attempt_id === attemptId) && typeof event.attempt_id === 'string' &&
            typeof event.event_id === 'string' &&
            typeof event.reason === 'string' && Number.isFinite(event.occurred_at_ms)) result.push(event);
      } catch { /* unrelated/malformed records are preserved, never executed */ }
    }
    return result;
  }
  remove(id: string): void { this.storage.removeItem(PREFIX + id); }
}

/** Lives above the workspace so failures still retry after opening a report. */
export class DurableInterruptionQueue {
  private memory = new Map<string, PendingInterruption>();
  private inFlight: Promise<void> | null = null;
  private outbox: InterruptionOutbox | null;
  constructor(outbox: InterruptionOutbox | null) { this.outbox = outbox; }
  add(event: PendingInterruption): void {
    this.memory.set(event.event_id, event);
    try { this.outbox?.add(event); } catch { /* keep the document copy */ }
  }
  pending(attemptId?: string): PendingInterruption[] {
    const records = new Map<string, PendingInterruption>();
    try { for (const event of this.outbox?.pending(attemptId) ?? []) records.set(event.event_id, event); }
    catch { /* browser storage may be unavailable */ }
    for (const event of this.memory.values())
      if (!attemptId || event.attempt_id === attemptId) records.set(event.event_id, event);
    return [...records.values()];
  }
  flush(deliver: (event: PendingInterruption) => Promise<boolean>,
    acknowledged: (event: PendingInterruption) => void): Promise<void> {
    if (this.inFlight) return this.inFlight;
    this.inFlight = (async () => {
      for (const event of this.pending()) {
        try {
          if (!await deliver(event)) continue;
          // A server acknowledgment is required, even after expiry or submit.
          this.outbox?.remove(event.event_id);
          this.memory.delete(event.event_id);
          acknowledged(event);
        } catch { /* keep the exact event ID and retry on the next cycle */ }
      }
    })().finally(() => { this.inFlight = null; });
    return this.inFlight;
  }
}

import { useEffect } from 'react';
import { api, ApiError } from '../../domain/http';
import { DurableInterruptionQueue, InterruptionOutbox, type PendingInterruption } from './interruptionOutbox';

let queue: DurableInterruptionQueue | undefined;
function deliveryQueue(): DurableInterruptionQueue {
  if (!queue) {
    let outbox: InterruptionOutbox | null = null;
    try { outbox = new InterruptionOutbox(window.localStorage); } catch { /* memory fallback */ }
    queue = new DurableInterruptionQueue(outbox);
  }
  return queue;
}
function changed(attemptId: string): void {
  window.dispatchEvent(new CustomEvent('toeic:interruption-updated', { detail: { attemptId } }));
}
export function pendingInterruptionCount(attemptId: string): number {
  return deliveryQueue().pending(attemptId).length;
}
export function queueInterruption(event: PendingInterruption): void {
  deliveryQueue().add(event);
  changed(event.attempt_id);
  void deliverInterruptions();
}
async function deliverInterruptions(): Promise<void> {
  await deliveryQueue().flush(async (event) => {
    try {
      const result = await api.interrupt(event.attempt_id, event.reason, {
        event_id: event.event_id, occurred_at_ms: event.occurred_at_ms,
      }, event.owner_tab_id);
      return result.timing.integrity === 'interrupted';
    } catch (error) {
      // A takeover already invalidates a strict exam. A former owner's event
      // can be cleared only after that durable reliability state is confirmed.
      if (error instanceof ApiError && error.code === 'tab_conflict') {
        const result = await api.getAttempt(event.attempt_id);
        return result.timing.integrity === 'interrupted';
      }
      throw error;
    }
  }, (event) => changed(event.attempt_id));
}

/** App-level courier remains mounted on report, home, history and settings. */
export function InterruptionDelivery() {
  useEffect(() => {
    const retry = () => { void deliverInterruptions(); };
    const storage = (change: StorageEvent) => {
      try {
        const event = JSON.parse(change.newValue ?? change.oldValue ?? '{}') as Partial<PendingInterruption>;
        if (typeof event.attempt_id === 'string') changed(event.attempt_id);
      } catch { /* unrelated browser storage */ }
      for (const event of deliveryQueue().pending()) changed(event.attempt_id);
      retry();
    };
    retry();
    const interval = window.setInterval(retry, 3000);
    window.addEventListener('online', retry);
    window.addEventListener('focus', retry);
    window.addEventListener('storage', storage);
    return () => {
      clearInterval(interval);
      window.removeEventListener('online', retry);
      window.removeEventListener('focus', retry);
      window.removeEventListener('storage', storage);
    };
  }, []);
  return null;
}

import type { ActivityEvent } from '../../domain/types';

/** One in-flight event. Pending transitions use the current target when sent;
 * a disconnected queue must never replay past question/view time. No retries. */
export class ActivityChannel {
  private session: string | null = null;
  private sequences = new Map<string, number>();
  private target: string | null = null;
  private pending = false;
  private sending = false;
  private send: (event: ActivityEvent) => Promise<void>;
  constructor(send: (event: ActivityEvent) => Promise<void>) { this.send = send; }
  select(session: string | null, target: string | null) {
    this.session = session;
    this.target = target;
    this.pending = !!session;
    void this.drain();
  }
  pulse() { if (this.session) { this.pending = true; void this.drain(); } }
  private async drain() {
    if (this.sending) return;
    this.sending = true;
    try {
      while (this.pending && this.session) {
        this.pending = false;
        const sequence = (this.sequences.get(this.session) ?? 0) + 1;
        this.sequences.set(this.session, sequence);
        const event = { session_id: this.session, sequence, question_id: this.target };
        try { await this.send(event); } catch { /* next live heartbeat replaces a failed event */ }
      }
    } finally { this.sending = false; }
  }
}

import type { AttemptReport } from '../../domain/types';
interface ReportRequestToken { attemptId: string; generation: number }

export class ReportRequestGate {
  private attemptId = '';
  private generation = 0;
  private active = true;
  private report: AttemptReport | null = null;
  select(id: string): void {
    if (id !== this.attemptId) {
      this.attemptId = id; this.report = null; this.generation++; this.active = true;
    }
  }
  activate(id: string): void {
    if (id !== this.attemptId) return;
    this.active = true; this.generation++;
  }
  begin(id: string): ReportRequestToken | null {
    // Only rendering/mounting selects the identity. A delayed child's save
    // callback must never re-select its old report or revive an unmounted one.
    if (!this.active || id !== this.attemptId) return null;
    return { attemptId: id, generation: ++this.generation };
  }
  current(token: ReportRequestToken | null): boolean {
    return this.active && token !== null && token.attemptId === this.attemptId && token.generation === this.generation;
  }
  accept(token: ReportRequestToken | null, incoming: AttemptReport): AttemptReport | null {
    if (!this.current(token) || incoming.attempt.id !== this.attemptId) return null;
    const previous = this.report;
    // Reliability can only become interrupted during a closed attempt. Even a
    // later clean snapshot must not re-enable review forms or the valid label.
    if (previous?.attempt.integrity === 'interrupted' && incoming.attempt.integrity !== 'interrupted') {
      incoming = { ...incoming, attempt: { ...incoming.attempt, integrity: 'interrupted',
        interruptions: previous.attempt.interruptions } };
    }
    this.report = incoming;
    return incoming;
  }
  invalidate(): void { this.active = false; this.generation++; }
}

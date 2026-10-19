interface Write {
  send: () => void | Promise<void>;
  failed: () => void;
}
interface Channel { pending: Write | null; running: boolean }

/** The attempt owns ordering; mounting a new audio controller cannot reset it. */
class MediaPersistence {
  private channels = new Map<string, Channel>();
  enqueue(attemptId: string, write: Write): void {
    let channel = this.channels.get(attemptId);
    if (!channel) {
      channel = { pending: null, running: false };
      this.channels.set(attemptId, channel);
    }
    // Newer playback/seek intent supersedes unsent positions, including those
    // queued by a controller that has since been destroyed.
    channel.pending = write;
    if (!channel.running) void this.drain(attemptId, channel);
  }
  private async drain(attemptId: string, channel: Channel): Promise<void> {
    channel.running = true;
    try {
      while (channel.pending) {
        const write = channel.pending; channel.pending = null;
        try { await write.send(); }
        catch {
          channel.pending ??= write;
          write.failed();
          break;
        }
      }
    } finally {
      channel.running = false;
      if (!channel.pending && this.channels.get(attemptId) === channel) this.channels.delete(attemptId);
    }
  }
}
export const mediaPersistence = new MediaPersistence();

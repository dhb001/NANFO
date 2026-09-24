// Realtime burst handling (ADR-028): frames are queued and applied once per
// animation frame. Hidden tabs do not paint, so a 250 ms timer bounds latency
// and memory there. The queue is bounded; overflow drops the oldest frames and
// reports it so the caller resynchronizes from REST.

export const FRAME_QUEUE_LIMIT = 5_000;
export const HIDDEN_FLUSH_MS = 250;

export type Scheduler = (flush: () => void) => () => void;

export function scheduleFrame(flush: () => void): () => void {
  let done = false;
  const run = () => {
    if (done) return;
    done = true;
    if (frame !== undefined) window.cancelAnimationFrame(frame);
    window.clearTimeout(timer);
    flush();
  };
  const frame = typeof window.requestAnimationFrame === "function" ? window.requestAnimationFrame(run) : undefined;
  const timer = window.setTimeout(run, HIDDEN_FLUSH_MS);
  return () => {
    done = true;
    if (frame !== undefined) window.cancelAnimationFrame(frame);
    window.clearTimeout(timer);
  };
}

export interface FrameQueue<T> {
  push: (item: T) => void;
  /** Apply everything queued now (for example before a context switch). */
  flush: () => void;
  /** Drop queued frames without applying them (context changed). */
  clear: () => void;
  size: () => number;
}

export function createFrameQueue<T>(
  onFlush: (items: T[], overflowed: boolean) => void,
  { limit = FRAME_QUEUE_LIMIT, schedule = scheduleFrame }: { limit?: number; schedule?: Scheduler } = {},
): FrameQueue<T> {
  let items: T[] = [];
  let overflowed = false;
  let cancel: (() => void) | null = null;
  const flush = () => {
    cancel?.();
    cancel = null;
    const batch = items;
    const lost = overflowed;
    items = [];
    overflowed = false;
    if (batch.length || lost) onFlush(batch, lost);
  };
  return {
    push: (item) => {
      items.push(item);
      if (items.length > limit) {
        // Drop a slab of the oldest frames at once: amortized O(1) under sustained overflow.
        items = items.slice(items.length - Math.max(1, Math.floor(limit * 0.9)));
        overflowed = true;
      }
      cancel ??= schedule(flush);
    },
    flush,
    clear: () => {
      cancel?.();
      cancel = null;
      items = [];
      overflowed = false;
    },
    size: () => items.length,
  };
}

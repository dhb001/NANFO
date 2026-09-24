import { afterEach, describe, expect, it, vi } from "vitest";
import { createFrameQueue, HIDDEN_FLUSH_MS, scheduleFrame } from "./frameQueue";

describe("realtime frame queue", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("coalesces any number of frames into one flush per scheduled frame", () => {
    const flushes: number[][] = [];
    let pending: (() => void) | null = null;
    const queue = createFrameQueue<number>((items) => flushes.push(items), { schedule: (flush) => { pending = flush; return () => { pending = null; }; } });
    for (let index = 0; index < 1_000; index++) queue.push(index);
    expect(flushes).toEqual([]);
    expect(queue.size()).toBe(1_000);
    pending!();
    expect(flushes).toHaveLength(1);
    expect(flushes[0]).toHaveLength(1_000);
    expect(flushes[0].at(-1)).toBe(999);
    queue.push(1_000);
    pending!();
    expect(flushes).toHaveLength(2);
  });

  it("is bounded: overflow drops the oldest frames and reports the gap", () => {
    const seen: Array<{ items: number[]; overflowed: boolean }> = [];
    const queue = createFrameQueue<number>((items, overflowed) => seen.push({ items, overflowed }), { limit: 100, schedule: () => () => undefined });
    for (let index = 0; index < 1_000; index++) queue.push(index);
    expect(queue.size()).toBeLessThanOrEqual(100);
    queue.flush();
    expect(seen).toHaveLength(1);
    expect(seen[0].overflowed).toBe(true);
    expect(seen[0].items.at(-1)).toBe(999);
    expect(seen[0].items.length).toBeLessThanOrEqual(100);
    queue.flush();
    expect(seen).toHaveLength(1);
  });

  it("clear drops queued frames without applying them", () => {
    const onFlush = vi.fn();
    const queue = createFrameQueue<number>(onFlush, { schedule: () => () => undefined });
    queue.push(1);
    queue.clear();
    queue.flush();
    expect(onFlush).not.toHaveBeenCalled();
  });

  it("flushes on the next animation frame, or after the hidden-tab fallback when frames do not paint", () => {
    vi.useFakeTimers();
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const painted = vi.fn();
    scheduleFrame(painted);
    frames[0](0);
    vi.advanceTimersByTime(HIDDEN_FLUSH_MS);
    expect(painted).toHaveBeenCalledTimes(1);
    const hidden = vi.fn();
    scheduleFrame(hidden);
    vi.advanceTimersByTime(HIDDEN_FLUSH_MS - 1);
    expect(hidden).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(hidden).toHaveBeenCalledTimes(1);
    frames[1](0);
    expect(hidden).toHaveBeenCalledTimes(1);
  });
});

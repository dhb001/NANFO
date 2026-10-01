import { Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CHUNK_RELOAD_KEY, lazyWithRetry, loadChunkWithRetry, type ChunkRetryEnvironment } from "./lazyWithRetry";

function environment(marker: string | null = null): ChunkRetryEnvironment & { values: Map<string, string> } {
  const values = new Map<string, string>(marker ? [[CHUNK_RELOAD_KEY, marker]] : []);
  return {
    values,
    storage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => { values.set(key, value); },
      removeItem: (key) => { values.delete(key); },
    },
    reload: vi.fn(),
    retryDelayMs: 0,
  };
}

const chunkError = () => new TypeError("Failed to fetch dynamically imported module: /assets/Page-old.js");

describe("route chunk retry (ADR-028)", () => {
  it("retries a transient chunk failure once without reloading and clears a stale marker", async () => {
    const env = environment("earlier");
    const load = vi.fn().mockRejectedValueOnce(chunkError()).mockResolvedValue({ default: "page" });
    await expect(loadChunkWithRetry(load, env)).resolves.toEqual({ default: "page" });
    expect(load).toHaveBeenCalledTimes(2);
    expect(env.reload).not.toHaveBeenCalled();
    expect(env.values.has(CHUNK_RELOAD_KEY)).toBe(false);
  });

  it("reloads once per session when the chunk is gone after a deploy, then surfaces the error", async () => {
    const env = environment();
    const load = vi.fn().mockRejectedValue(chunkError());
    const pending = loadChunkWithRetry(load, env);
    await vi.waitFor(() => expect(env.reload).toHaveBeenCalledTimes(1));
    expect(env.values.get(CHUNK_RELOAD_KEY)).toBeTruthy();
    let settled = false;
    void pending.then(() => { settled = true; }, () => { settled = true; });
    await Promise.resolve();
    expect(settled).toBe(false);
    // After the reload the marker is present: no second reload (no loop), the boundary shows the error.
    await expect(loadChunkWithRetry(load, env)).rejects.toThrow("Failed to fetch dynamically imported module");
    expect(env.reload).toHaveBeenCalledTimes(1);
  });

  it("never retries or reloads for ordinary errors or without session storage", async () => {
    const env = environment();
    const failure = vi.fn().mockRejectedValue(new Error("render bug"));
    await expect(loadChunkWithRetry(failure, env)).rejects.toThrow("render bug");
    expect(failure).toHaveBeenCalledTimes(1);
    const noStorage = { ...environment(), storage: null };
    await expect(loadChunkWithRetry(vi.fn().mockRejectedValue(chunkError()), noStorage)).rejects.toThrow();
    expect(noStorage.reload).not.toHaveBeenCalled();
  });

  it("renders a lazy route after a transient failure instead of caching the rejection", async () => {
    const env = environment();
    const load = vi.fn().mockRejectedValueOnce(chunkError()).mockResolvedValue({ default: () => <p>Route ready</p> });
    const Page = lazyWithRetry(load, env);
    render(<Suspense fallback={<p>Loading</p>}><Page /></Suspense>);
    expect(await screen.findByText("Route ready")).toBeInTheDocument();
    expect(env.reload).not.toHaveBeenCalled();
  });
});

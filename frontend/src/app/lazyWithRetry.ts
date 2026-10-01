import { lazy, type ComponentType } from "react";
import { isChunkLoadError } from "@/shared/lib/chunkErrors";

/** sessionStorage marker: one automatic reload per browser session for chunk failures. */
export const CHUNK_RELOAD_KEY = "nanfo.chunk-reload";

export interface ChunkRetryEnvironment {
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  reload: () => void;
  retryDelayMs: number;
}

function browserEnvironment(): ChunkRetryEnvironment {
  let storage: ChunkRetryEnvironment["storage"] = null;
  try { storage = window.sessionStorage; } catch { /* storage disabled: no automatic reload */ }
  return { storage, reload: () => window.location.reload(), retryDelayMs: 500 };
}

/**
 * Load a route chunk, surviving the two common failures: a transient network error (one
 * immediate retry) and a deploy that removed the old chunk names (one page reload per
 * session, guarded by sessionStorage so a broken deploy cannot reload-loop). Anything
 * else, or a second failure after the reload, reaches the route error boundary.
 */
export async function loadChunkWithRetry<T>(load: () => Promise<T>, environment: ChunkRetryEnvironment = browserEnvironment()): Promise<T> {
  let result: T;
  try {
    result = await load();
  } catch (first) {
    if (!isChunkLoadError(first)) throw first;
    await new Promise((resolve) => setTimeout(resolve, environment.retryDelayMs));
    try {
      result = await load();
    } catch (second) {
      if (!isChunkLoadError(second)) throw second;
      let reloaded = true;
      try { reloaded = environment.storage?.getItem(CHUNK_RELOAD_KEY) !== null; } catch { reloaded = true; }
      if (environment.storage && !reloaded) {
        environment.storage.setItem(CHUNK_RELOAD_KEY, new Date().toISOString());
        environment.reload();
        // Keep the Suspense fallback up while the page reloads.
        return new Promise<T>(() => undefined);
      }
      throw second;
    }
  }
  try { environment.storage?.removeItem(CHUNK_RELOAD_KEY); } catch { /* ignore */ }
  return result;
}

/** `React.lazy` caches a rejected import forever, so route chunks load through `loadChunkWithRetry`. */
export function lazyWithRetry<T extends ComponentType<any>>(load: () => Promise<{ default: T }>, environment?: ChunkRetryEnvironment) {
  return lazy(() => loadChunkWithRetry(load, environment));
}

export interface BackoffOptions {
  baseMs?: number;
  capMs?: number;
  /** Uniform [0, 1) source; injectable for deterministic tests. */
  random?: () => number;
}

/**
 * Capped exponential backoff with FULL jitter: a uniform delay in
 * [0, min(cap, base * 2^(attempt - 1))). Spreading every client across the whole
 * window avoids synchronized reconnect storms after a shared outage (ADR-028 C1).
 */
export function nextBackoffMs(attempt: number, { baseMs = 500, capMs = 30_000, random = Math.random }: BackoffOptions = {}): number {
  const ceiling = Math.min(capMs, baseMs * 2 ** Math.max(0, attempt - 1));
  return Math.floor(Math.min(Math.max(random(), 0), 1) * ceiling);
}

/** Milliseconds requested by an HTTP `Retry-After` header (delta-seconds or HTTP-date), bounded; null when absent/invalid. */
export function retryAfterMs(header: string | null | undefined, now = Date.now(), maxMs = 300_000): number | null {
  if (!header) return null;
  const value = header.trim();
  const delay = /^\d+$/.test(value) ? Number(value) * 1000 : Date.parse(value) - now;
  return Number.isFinite(delay) ? Math.min(Math.max(delay, 0), maxMs) : null;
}

import type { QueryKey } from "@tanstack/react-query";

/** Session identity used in query keys: never the credential (ADR-028). */
export interface KeyScope {
  key: string;
  authority: string;
}

/** Uniform layout for server reads: `[domain, sessionKey, authority, ...params]`. */
export function scopedKey(scope: KeyScope, domain: string, ...params: unknown[]): QueryKey {
  return [domain, scope.key, scope.authority, ...params];
}

/** True when `key` belongs to `scope` (and optionally `domain`). Params start at index 3. */
export function isScopedKey(key: QueryKey, scope: KeyScope, domain?: string): boolean {
  return key[1] === scope.key && key[2] === scope.authority && (domain === undefined || key[0] === domain);
}

/**
 * `keepPreviousData` restricted to the same paginated series: only the value at
 * `pageIndex` may differ. A tenant, filter or identity change shows loading
 * instead of another series' rows.
 */
export function samePageSeries(previous: QueryKey | undefined, next: QueryKey, pageIndex: number): boolean {
  if (!previous || previous.length !== next.length) return false;
  return previous.every((part, index) => index === pageIndex || JSON.stringify(part) === JSON.stringify(next[index]));
}

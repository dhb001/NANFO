/**
 * API and WebSocket base URLs (ADR-028 C16).
 *
 * Production builds default to the same origin: the gateway serves the UI,
 * `/api` and `/ws` together, so the API base is `""` and the WebSocket base is
 * derived from `window.location` (`wss:` on `https:`). An explicit
 * `VITE_API_BASE_URL` / `VITE_WS_BASE_URL` still overrides at build time;
 * `vite.config.ts` refuses production builds whose override targets loopback.
 */

const WS_SCHEMES: Record<string, string> = { "http:": "ws:", "https:": "wss:", "ws:": "ws:", "wss:": "wss:" };

type OriginLocation = Pick<Location, "protocol" | "host">;

/** Trim whitespace and trailing slashes; anything unset/blank means same-origin (`""`). */
export function normalizeBaseUrl(value: unknown): string {
  return typeof value === "string" ? value.trim().replace(/\/+$/, "") : "";
}

function isAbsolute(base: string) {
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(base);
}

/** WebSocket base for an explicit override, else derived from the API base, else from the page origin. */
export function resolveWebSocketBase(configuredWs: unknown, apiBase: string, location: OriginLocation): string {
  const explicit = normalizeBaseUrl(configuredWs);
  const base = explicit || normalizeBaseUrl(apiBase);
  if (isAbsolute(base)) {
    const url = new URL(base);
    url.protocol = WS_SCHEMES[url.protocol] ?? url.protocol;
    return normalizeBaseUrl(url.toString());
  }
  // "" or a same-origin path prefix such as "/nanfo".
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  const prefix = base && !base.startsWith("/") ? `/${base}` : base;
  return `${scheme}//${location.host}${prefix}`;
}

export const API_BASE_URL: string = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);

/** Absolute or same-origin URL for an API path such as `/api/v1/auth/me`. */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

/** Resolved at call time so tests and gateway deployments always see the current origin. */
export function webSocketBaseUrl(location: OriginLocation = window.location): string {
  return resolveWebSocketBase(import.meta.env.VITE_WS_BASE_URL, API_BASE_URL, location);
}

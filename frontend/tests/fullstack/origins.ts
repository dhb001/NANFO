// C22 (ADR-028): the production build is served through the real gateway, so the API and
// WebSocket share the page origin (Playwright baseURL). R09_API_URL keeps the older
// cross-origin lane (UI and API on different loopback ports) working as an explicit override.

export function loopbackOrigin(name: string, value: string | undefined): string {
  if (!value) throw new Error(`R09 missing ${name}; use backend/scripts/review_fullstack.py`);
  const url = new URL(value);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port || url.pathname !== "/" || url.username || url.password || url.search || url.hash) {
    throw new Error(`R09 requires a bare owned loopback origin for ${name}`);
  }
  return url.origin;
}

export interface R09Origins {
  /** Page origin (Playwright baseURL). */
  base: string;
  /** Where the UI's API requests go: the page origin unless R09_API_URL overrides it. */
  api: string;
  /** Where the UI's WebSockets go (derived from the API origin, like the app does). */
  ws: string;
  sameOrigin: boolean;
}

export function resolveOrigins(env: Record<string, string | undefined>): R09Origins {
  const base = loopbackOrigin("R09_BASE_URL", env.R09_BASE_URL);
  const api = env.R09_API_URL ? loopbackOrigin("R09_API_URL", env.R09_API_URL) : base;
  return { base, api, ws: api.replace(/^http/, "ws"), sameOrigin: api === base };
}

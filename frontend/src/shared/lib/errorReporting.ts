import { randomId } from "@/shared/lib/uid";

/** A rendering failure operators can quote to support (ADR-028). */
export interface UiIncident {
  incidentId: string;
  kind: "chunk" | "render";
  /** Error class name only: messages and stacks can carry URLs, tokens or tenant data. */
  errorName: string;
  path: string;
  at: string;
  /** Most recent backend `meta.request_id`, to correlate with server logs. */
  lastRequestId: string | null;
}

let lastRequestId: string | null = null;
const listeners = new Set<(incident: UiIncident) => void>();

/** Called by the API client for every response carrying a request id. */
export function noteServerRequestId(requestId: string | null | undefined): void {
  if (typeof requestId === "string" && requestId && requestId.length <= 128) lastRequestId = requestId;
}

export function onUiIncident(listener: (incident: UiIncident) => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function reportUiIncident(error: unknown, kind: UiIncident["kind"]): UiIncident {
  const incident: UiIncident = {
    incidentId: randomId("ui"),
    kind,
    errorName: error instanceof Error ? error.name : typeof error,
    path: typeof window === "undefined" ? "" : window.location.pathname,
    at: new Date().toISOString(),
    lastRequestId,
  };
  console.error("[nanfo] ui incident", incident);
  for (const listener of listeners) {
    try { listener(incident); } catch { /* reporting never throws into rendering */ }
  }
  return incident;
}

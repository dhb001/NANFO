/**
 * Explicit presentation maps for backend-owned lifecycle states shown by the Twin.
 *
 * Rendering components must not guess meaning from substrings of backend strings
 * (for example `status.includes("failed")`). Every recognised value is listed here,
 * keyed exactly as the backend emits it; anything else is rendered neutrally and
 * labelled with its raw value so an unknown state is never shown as healthy or failed.
 *
 * Sources (backend is authoritative):
 * - simulation `state`: backend simulation service/modeled transitions and
 *   `app/modules/simulation/queries.py` TERMINAL_STATUSES (docs/api/WebSocket.md §4).
 * - intent `status`: backend intent service transitions and
 *   `app/modules/intent/queries.py` SAFE_TERMINAL_STATUSES / RESTORATION_STATUSES.
 * - device `status`: network inventory statuses used by topology nodes.
 */

export type TwinTone = "ok" | "warn" | "danger" | "info" | "neutral";

export const SIMULATION_STATE_TONES: Readonly<Record<string, TwinTone>> = Object.freeze({
  draft: "neutral",
  pending: "neutral",
  queued: "warn",
  running: "info",
  paused: "warn",
  completed: "ok",
  failed: "danger",
  cancelled: "danger",
});

export const INTENT_STATUS_TONES: Readonly<Record<string, TwinTone>> = Object.freeze({
  draft: "neutral",
  pending: "neutral",
  validated: "ok",
  deferred: "warn",
  queued: "warn",
  rejected: "danger",
  execution_started: "info",
  execution_completed: "ok",
  execution_failed: "danger",
  execution_cancelled: "danger",
  execution_compensated: "warn",
  cancelled: "danger",
  compensated: "warn",
});

export const DEVICE_STATUS_TONES: Readonly<Record<string, TwinTone>> = Object.freeze({
  active: "ok",
  offline: "warn",
  deleted: "danger",
});

/** Tone colours used inside the 3D scene (the DOM uses the badge classes instead). */
export const TONE_COLORS: Readonly<Record<Exclude<TwinTone, "info" | "neutral">, string>> = Object.freeze({
  ok: "#2ca774",
  warn: "#d1780f",
  danger: "#c93f2e",
});

/** Neutral/in-progress overlay colours keep simulation and intent objects distinguishable. */
export const OVERLAY_BASE_COLORS: Readonly<Record<"intent_state" | "simulation_state" | "other", string>> = Object.freeze({
  intent_state: "#2873cb",
  simulation_state: "#2f8f99",
  other: "#2f8f99",
});

function lookup(map: Readonly<Record<string, TwinTone>>, value: string | null | undefined): TwinTone {
  if (typeof value !== "string") return "neutral";
  return Object.hasOwn(map, value) ? map[value] : "neutral";
}

export interface OverlayStateLike {
  objectType: string;
  status: string | null;
  state: string | null;
}

/** The backend lifecycle value that drives an overlay: simulations report `state`, intents `status`. */
export function overlayLifecycleValue(overlay: OverlayStateLike): string | null {
  if (overlay.objectType === "simulation_state") return overlay.state ?? overlay.status;
  return overlay.status ?? overlay.state;
}

export function overlayTone(overlay: OverlayStateLike): TwinTone {
  const value = overlayLifecycleValue(overlay);
  if (overlay.objectType === "simulation_state") return lookup(SIMULATION_STATE_TONES, value);
  if (overlay.objectType === "intent_state") return lookup(INTENT_STATUS_TONES, value);
  return "neutral";
}

export function overlayColor(overlay: OverlayStateLike): string {
  const tone = overlayTone(overlay);
  if (tone === "ok" || tone === "warn" || tone === "danger") return TONE_COLORS[tone];
  return overlay.objectType === "intent_state" ? OVERLAY_BASE_COLORS.intent_state
    : overlay.objectType === "simulation_state" ? OVERLAY_BASE_COLORS.simulation_state : OVERLAY_BASE_COLORS.other;
}

export function deviceStatusTone(status: string | null | undefined): TwinTone {
  return lookup(DEVICE_STATUS_TONES, status);
}

export type ImportedModelStatus = "idle" | "loading" | "ready" | "error";
export const MODEL_STATUS_TONES: Readonly<Record<ImportedModelStatus, TwinTone>> = Object.freeze({
  idle: "neutral",
  loading: "warn",
  ready: "ok",
  error: "danger",
});

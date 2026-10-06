/**
 * Intent form prefill handed over from another in-app view (Digital Twin).
 *
 * Preferred transport is router state (`navigate("/ops/intent", { state: intentHandoffState(prefill) })`):
 * it never appears in URLs, history exports, logs or referrers. The legacy query-string form
 * (`?source=digital-twin&scope=...`) is still read for old links but is attacker-controllable,
 * so it is always marked untrusted. Either way the operator reviews every field before
 * validation, and a prefill never selects approval.
 */
export interface IntentPrefill {
  source: "digital-twin";
  /** Pre-selected action, or null (the Twin does not recommend one). */
  action: string | null;
  scopeJson: string;
  constraintsJson: string;
  contextSummary: string;
}

export interface IntentPrefillReading extends IntentPrefill {
  /** True when the content came from the URL (a link anyone can craft). */
  untrusted: boolean;
}

export const INTENT_HANDOFF_STATE_KEY = "intentHandoff";

/** Actions the form offers; anything else in a prefill is ignored. */
export const INTENT_FORM_ACTIONS = ["reroute_path", "isolate_vlan", "optimize_wireless_capacity", "throttle_qos"] as const;

// The backend refuses intent payloads over 64 KiB; the summary is display-only.
const MAX_JSON_CHARS = 64 * 1024;
const MAX_SUMMARY_CHARS = 500;

export function intentHandoffState(prefill: IntentPrefill): { [INTENT_HANDOFF_STATE_KEY]: IntentPrefill } {
  return { [INTENT_HANDOFF_STATE_KEY]: prefill };
}

function boundedText(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

function normalize(raw: Record<string, unknown>, untrusted: boolean): IntentPrefillReading | null {
  if (raw.source !== "digital-twin") return null;
  const action = typeof raw.action === "string" && (INTENT_FORM_ACTIONS as readonly string[]).includes(raw.action.trim()) ? raw.action.trim() : null;
  const scopeJson = typeof raw.scopeJson === "string" && raw.scopeJson.length <= MAX_JSON_CHARS ? raw.scopeJson : "";
  const constraintsJson = typeof raw.constraintsJson === "string" && raw.constraintsJson.length <= MAX_JSON_CHARS ? raw.constraintsJson : "";
  return { source: "digital-twin", action, scopeJson, constraintsJson, contextSummary: boundedText(raw.contextSummary, MAX_SUMMARY_CHARS).trim(), untrusted };
}

/** Prefill carried in router state by an in-app navigation, or null. */
export function readIntentHandoffState(state: unknown): IntentPrefillReading | null {
  if (!state || typeof state !== "object") return null;
  const raw = (state as Record<string, unknown>)[INTENT_HANDOFF_STATE_KEY];
  return raw && typeof raw === "object" && !Array.isArray(raw) ? normalize(raw as Record<string, unknown>, false) : null;
}

export const HANDOFF_QUERY_PARAMS = ["source", "action", "scope", "constraints", "context_summary"] as const;

/** Legacy query-string prefill: always untrusted. */
export function readUntrustedIntentQuery(search: string): IntentPrefillReading | null {
  const params = new URLSearchParams(search);
  if (params.get("source") !== "digital-twin") return null;
  return normalize({
    source: "digital-twin",
    action: params.get("action"),
    scopeJson: params.get("scope") ?? "",
    constraintsJson: params.get("constraints") ?? "",
    contextSummary: params.get("context_summary") ?? "",
  }, true);
}

/**
 * Explicit presentation tones for backend-owned lifecycle values (ADR-028).
 *
 * Each map lists exactly the values the backend emits for one field; the source
 * of every value set is noted on the map. Anything else (a newer backend state,
 * a legacy row, a typo) is "neutral" and callers show the raw value, so an
 * unrecognised state is never presented as healthy or as failed. Never derive
 * meaning from substrings or invented aliases of backend strings.
 */
import type { Schema } from "@/shared/types/contracts";

export type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral";
export type ToneMap = Readonly<Record<string, StatusTone>>;

function toneMap<const T extends Record<string, StatusTone>>(map: T): Readonly<T> {
  return Object.freeze(map);
}

/** Tone of `value` in `map`; unknown, empty or non-string values are "neutral". */
export function toneFor(map: ToneMap, value: unknown): StatusTone {
  return typeof value === "string" && Object.hasOwn(map, value) ? map[value] ?? "neutral" : "neutral";
}

/** `intents.status`: backend/app/modules/intent/models.py INTENT_STATUSES (CHECK ck_intents_status). */
export const INTENT_STATUS_TONES = toneMap({
  draft: "neutral",
  validated: "ok",
  rejected: "danger",
  execution_started: "info",
  execution_completed: "ok",
  execution_failed: "danger",
  cancelled: "warn",
  execution_cancelled: "warn",
  compensated: "warn",
  execution_compensated: "warn",
});

/** `intents.queue_status`: intent/models.py INTENT_QUEUE_STATUSES (CHECK ck_intents_queue_status). */
export const INTENT_QUEUE_STATUS_TONES = toneMap({
  pending: "neutral",
  validated: "info",
  outbox_pending: "info",
  queued: "ok",
  deferred: "warn",
});

/** Intent `confidence.band`: intent/service.py `_confidence_band` ("below_60" also marks refused executions). */
export const INTENT_CONFIDENCE_BAND_TONES = toneMap({
  "95-100": "ok",
  "80-94": "ok",
  "60-79": "warn",
  below_60: "danger",
});

/** `simulations.state`/`status`: simulation/models.py SIMULATION_STATES (CHECK ck_simulations_state). */
export const SIMULATION_STATE_TONES = toneMap({
  draft: "neutral",
  queued: "info",
  running: "info",
  paused: "warn",
  completed: "ok",
  cancelled: "danger",
  failed: "danger",
});

/** Simulation `queue_status`: simulation service/modeled writers (pending, draft, outbox_pending, queued, deferred). */
export const SIMULATION_QUEUE_STATUS_TONES = toneMap({
  pending: "neutral",
  draft: "neutral",
  outbox_pending: "info",
  queued: "ok",
  deferred: "warn",
});

/** Simulation `risk_gate`: "required" until evaluated, then evaluator "passed"/"blocked". */
export const SIMULATION_RISK_GATE_TONES = toneMap({
  required: "warn",
  passed: "ok",
  blocked: "danger",
});

/** `reports.status`: report/models.py CHECK ck_reports_status. */
export const REPORT_STATUS_TONES = toneMap({
  requested: "info",
  running: "info",
  generated: "ok",
  failed: "danger",
});

/** `reports.queue_status`: report service/repository (pending -> outbox_pending -> queued). */
export const REPORT_QUEUE_STATUS_TONES = toneMap({
  pending: "neutral",
  outbox_pending: "info",
  queued: "ok",
});

/** `alerts.status`: alert/models.py CHECK ck_alerts_status. */
export const ALERT_STATUS_TONES = toneMap({
  active: "warn",
  acknowledged: "info",
  resolved: "ok",
});

/**
 * Alert `severity`: the backend's closed filter vocabulary (report/schemas.py
 * ReportFilters.alert_severity) plus producer values (measured detector
 * "warning"; telemetry SLO evaluator ok/degraded/critical).
 */
export const ALERT_SEVERITY_TONES = toneMap({
  critical: "danger",
  high: "danger",
  degraded: "warn",
  medium: "warn",
  warning: "warn",
  low: "info",
  info: "info",
  ok: "ok",
});

/** `GET /telemetry/health` `status`: telemetry/health.py (ok, degraded, unavailable). */
export const TELEMETRY_HEALTH_TONES = toneMap({
  ok: "ok",
  degraded: "warn",
  unavailable: "warn",
});

/** Telemetry health `slo.status`: telemetry/schemas.py TelemetrySLOHealth.status Literal. */
export const TELEMETRY_SLO_TONES = toneMap({
  ok: "ok",
  degraded: "warn",
  critical: "danger",
  unavailable: "warn",
} satisfies Record<Schema<"TelemetrySLOHealth">["status"], StatusTone>);

/** Device `status`: network inventory (created "active", soft-deleted "deleted"). */
export const DEVICE_STATUS_TONES = toneMap({
  active: "ok",
  deleted: "danger",
});

/** Plugin registry `status`: plugin/schemas.py PluginRecordResponse.status Literal (metadata flags only). */
export const PLUGIN_STATUS_TONES = toneMap({
  installed: "info",
  enabled: "info",
  disabled: "neutral",
  failed: "danger",
  uninstalled: "neutral",
} satisfies Record<Schema<"PluginRecordResponse">["status"], StatusTone>);

export const intentStatusTone = (value: unknown) => toneFor(INTENT_STATUS_TONES, value);
export const intentQueueStatusTone = (value: unknown) => toneFor(INTENT_QUEUE_STATUS_TONES, value);
export const intentConfidenceBandTone = (value: unknown) => toneFor(INTENT_CONFIDENCE_BAND_TONES, value);
export const simulationStateTone = (value: unknown) => toneFor(SIMULATION_STATE_TONES, value);
export const simulationQueueStatusTone = (value: unknown) => toneFor(SIMULATION_QUEUE_STATUS_TONES, value);
export const simulationRiskGateTone = (value: unknown) => toneFor(SIMULATION_RISK_GATE_TONES, value);
export const reportStatusTone = (value: unknown) => toneFor(REPORT_STATUS_TONES, value);
export const reportQueueStatusTone = (value: unknown) => toneFor(REPORT_QUEUE_STATUS_TONES, value);
export const alertStatusTone = (value: unknown) => toneFor(ALERT_STATUS_TONES, value);
export const alertSeverityTone = (value: unknown) => toneFor(ALERT_SEVERITY_TONES, value);
export const telemetryHealthTone = (value: unknown) => toneFor(TELEMETRY_HEALTH_TONES, value);
export const telemetrySloTone = (value: unknown) => toneFor(TELEMETRY_SLO_TONES, value);
export const deviceStatusTone = (value: unknown) => toneFor(DEVICE_STATUS_TONES, value);
export const pluginStatusTone = (value: unknown) => toneFor(PLUGIN_STATUS_TONES, value);

/** Display text for a backend value: the raw value, or an explicit placeholder when absent. */
export function statusLabel(value: unknown, missing = "unknown"): string {
  return typeof value === "string" && value.trim() ? value : missing;
}

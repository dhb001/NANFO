/**
 * Twin severity sources, in order of authority.
 *
 * 1. **Backend alert state (authoritative).** Active/acknowledged alerts from the Alert
 *    module (REST snapshot + `/ws/alerts` deltas). Only these say a device is in breach.
 * 2. **Visual heuristic (display only).** A single-sample colouring of live telemetry that
 *    mirrors the backend detector's *default* thresholds exactly
 *    (`backend/app/modules/alert/detector.py`: `DetectorSettings` + `METRICS`). It is not an
 *    alert, it ignores the detector's sample/duration window, deployments may override the
 *    backend values with `ALERT_*` settings, and it must never be sent as a policy.
 */

export interface DetectorRuleMirror {
  id: "utilization" | "latency" | "loss" | "queue";
  label: string;
  unit: string;
  breach: number;
  recover: number;
}

export const BACKEND_DETECTOR_RULES: Readonly<Record<string, DetectorRuleMirror>> = Object.freeze({
  link_utilization_percent: Object.freeze({ id: "utilization", label: "Link utilization", unit: "%", breach: 85, recover: 70 }),
  latency_ms: Object.freeze({ id: "latency", label: "Latency", unit: "ms", breach: 100, recover: 70 }),
  packet_loss_percent: Object.freeze({ id: "loss", label: "Packet loss", unit: "%", breach: 2, recover: 1 }),
  queue_backlog_packets: Object.freeze({ id: "queue", label: "Queue backlog", unit: "packets", breach: 80, recover: 40 }),
} satisfies Record<string, DetectorRuleMirror>);

export const VISUAL_HEURISTIC_ID = "visual-heuristic.backend-detector-defaults.v1";
export const VISUAL_HEURISTIC_LABEL = "Visual heuristic";

/** Same phase semantics as `advance_window`: breach `>= breach`, recovery `< recover`. */
export type HeuristicLevel = "above_breach" | "between_thresholds" | "below_recovery";
export type HeuristicSeverity = "high" | "medium" | "low";

export const HEURISTIC_LEVEL_SEVERITY: Readonly<Record<HeuristicLevel, HeuristicSeverity>> = Object.freeze({
  above_breach: "high",
  between_thresholds: "medium",
  below_recovery: "low",
});

export const HEURISTIC_LEVEL_TEXT: Readonly<Record<HeuristicLevel, string>> = Object.freeze({
  above_breach: "at or above backend breach threshold",
  between_thresholds: "between backend recovery and breach thresholds",
  below_recovery: "below backend recovery threshold",
});

export function detectorRuleFor(metric: string, unit: string | null): DetectorRuleMirror | null {
  if (!Object.hasOwn(BACKEND_DETECTOR_RULES, metric)) return null;
  const rule = BACKEND_DETECTOR_RULES[metric];
  return unit === rule.unit ? rule : null;
}

export function visualHeuristicLevel(metric: string, unit: string | null, value: number): { rule: DetectorRuleMirror; level: HeuristicLevel } | null {
  const rule = detectorRuleFor(metric, unit);
  if (!rule || typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  const level: HeuristicLevel = value >= rule.breach ? "above_breach" : value < rule.recover ? "below_recovery" : "between_thresholds";
  return { rule, level };
}

export function describeDetectorRule(metric: string, rule: DetectorRuleMirror): string {
  return `${rule.label} (${metric}): breach ≥ ${rule.breach} ${rule.unit}, recovery < ${rule.recover} ${rule.unit}`;
}

// --------------------------------------------------------------------------------------
// Backend alert state
// --------------------------------------------------------------------------------------

export interface AlertEventLike {
  event_type: string;
  payload: Record<string, unknown>;
  timestamp?: string;
}

export interface AlertRecordLike {
  alert_id: string;
  alert_key: string;
  status: string;
  severity: string | null;
  payload: Record<string, unknown>;
  updated_at: string;
}

export type BackendAlertStatus = "active" | "acknowledged";

export interface BackendDeviceAlert {
  key: string;
  alertId: string | null;
  alertKey: string | null;
  deviceId: string;
  status: BackendAlertStatus;
  severity: string | null;
  metric: string | null;
  value: number | null;
  unit: string | null;
  breach: number | null;
  recover: number | null;
  origin: "rest" | "live";
}

export interface DeviceAlertSummary {
  deviceId: string;
  /** `active` when any alert is active; `acknowledged` when all open alerts are acknowledged. */
  status: BackendAlertStatus;
  alerts: BackendDeviceAlert[];
}

const EVENT_STATUS: Readonly<Record<string, BackendAlertStatus | "resolved">> = Object.freeze({
  "alert.generated": "active",
  "alert.acknowledged": "acknowledged",
  "alert.resolved": "resolved",
});

const RECORD_STATUS: Readonly<Record<string, BackendAlertStatus | "resolved">> = Object.freeze({
  active: "active",
  acknowledged: "acknowledged",
  ack: "acknowledged",
  resolved: "resolved",
});

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Device reference carried by alert payloads (measured detector alerts use `device_id`). */
export function alertDeviceId(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload || typeof payload !== "object") return null;
  const scope = payload.scope && typeof payload.scope === "object" && !Array.isArray(payload.scope)
    ? payload.scope as Record<string, unknown> : null;
  return text(payload.device_id) ?? text(payload.deviceId) ?? text(payload.target_device_id) ?? text(scope?.device_id);
}

function entryFrom(payload: Record<string, unknown>, deviceId: string, key: string, status: BackendAlertStatus,
  origin: "rest" | "live", overrides: { alertId?: string | null; alertKey?: string | null; severity?: string | null } = {}): BackendDeviceAlert {
  const rule = payload.rule && typeof payload.rule === "object" && !Array.isArray(payload.rule) ? payload.rule as Record<string, unknown> : null;
  return {
    key,
    alertId: overrides.alertId ?? text(payload.alert_id),
    alertKey: overrides.alertKey ?? text(payload.alert_key),
    deviceId,
    status,
    severity: overrides.severity ?? text(payload.severity),
    metric: text(payload.metric),
    value: finite(payload.value),
    unit: text(payload.unit),
    breach: finite(rule?.breach),
    recover: finite(rule?.recover),
    origin,
  };
}

function timestampOf(value: string | null | undefined): number {
  const parsed = Date.parse(value ?? "");
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

/**
 * Merge the REST snapshot of open alerts with realtime lifecycle events.
 *
 * Alerts are tracked per alert identity (`alert_id`, then `alert_key`, then the device for
 * legacy payloads), so resolving one of a device's alerts never hides another open alert.
 * Live events are newest-first; a live event older than the REST record's `updated_at` is
 * ignored. When a live event has no timestamp it is treated as the newer observation.
 */
export function deriveDeviceAlertStates(
  restAlerts: readonly AlertRecordLike[] | undefined,
  liveAlerts: readonly AlertEventLike[],
  knownDeviceIds?: ReadonlySet<string>,
): Map<string, DeviceAlertSummary> {
  const latest = new Map<string, { at: number; status: BackendAlertStatus | "resolved"; entry: BackendDeviceAlert | null }>();
  for (const record of restAlerts ?? []) {
    const status = RECORD_STATUS[(record.status ?? "").trim().toLowerCase()];
    const deviceId = alertDeviceId(record.payload);
    if (!status || !deviceId) continue;
    const key = text(record.alert_id) ?? text(record.alert_key) ?? `device:${deviceId}`;
    const entry = status === "resolved" ? null : entryFrom(record.payload ?? {}, deviceId, key, status, "rest",
      { alertId: text(record.alert_id), alertKey: text(record.alert_key), severity: text(record.severity) });
    latest.set(key, { at: timestampOf(record.updated_at), status, entry });
  }
  const seenLive = new Set<string>();
  for (const alert of liveAlerts) {
    const status = Object.hasOwn(EVENT_STATUS, alert.event_type) ? EVENT_STATUS[alert.event_type] : undefined;
    const payload = alert.payload && typeof alert.payload === "object" ? alert.payload : {};
    const deviceId = alertDeviceId(payload);
    if (!status || !deviceId) continue;
    const key = text(payload.alert_id) ?? text(payload.alert_key) ?? `device:${deviceId}`;
    if (seenLive.has(key)) continue;
    seenLive.add(key);
    const at = timestampOf(alert.timestamp);
    const existing = latest.get(key);
    if (existing && at !== Number.NEGATIVE_INFINITY && at < existing.at) continue;
    latest.set(key, { at, status, entry: status === "resolved" ? null : entryFrom(payload, deviceId, key, status, "live") });
  }
  const summaries = new Map<string, DeviceAlertSummary>();
  for (const { entry } of latest.values()) {
    if (!entry || (knownDeviceIds && !knownDeviceIds.has(entry.deviceId))) continue;
    const summary = summaries.get(entry.deviceId) ?? { deviceId: entry.deviceId, status: "acknowledged" as BackendAlertStatus, alerts: [] };
    summary.alerts.push(entry);
    if (entry.status === "active") summary.status = "active";
    summaries.set(entry.deviceId, summary);
  }
  for (const summary of summaries.values()) {
    summary.alerts.sort((left, right) => (left.status === right.status ? 0 : left.status === "active" ? -1 : 1)
      || (left.metric ?? "").localeCompare(right.metric ?? "") || left.key.localeCompare(right.key));
  }
  return summaries;
}

/** Devices with at least one *active* (unacknowledged, unresolved) backend alert. */
export function activeAlertDeviceIds(states: ReadonlyMap<string, DeviceAlertSummary>): Set<string> {
  const ids = new Set<string>();
  for (const summary of states.values()) if (summary.status === "active") ids.add(summary.deviceId);
  return ids;
}

export function describeDeviceAlerts(summary: DeviceAlertSummary | undefined): string {
  if (!summary || summary.alerts.length === 0) return "No open backend alerts";
  const active = summary.alerts.filter((alert) => alert.status === "active").length;
  const acknowledged = summary.alerts.length - active;
  return [active ? `${active} active` : null, acknowledged ? `${acknowledged} acknowledged` : null]
    .filter(Boolean).join(", ") + ` backend alert${summary.alerts.length === 1 ? "" : "s"}`;
}

import type { BackendDeviceAlert } from "@/features/digitalTwin/twinSeverity";

/**
 * Digital Twin -> Intent prefill. The operator reviews and edits everything before
 * validation. Only backend-owned facts are carried: device identity, the persisted
 * spatial reference and references to open backend alerts. The Twin's visual heuristic
 * is display-only and is never embedded (no policy id, score or heuristic severity), and
 * no action is pre-selected from it.
 */
export interface IntentHandoffPrefill {
  source: "digital-twin";
  /** Always null: the Twin does not recommend an action. */
  action: null;
  scopeJson: string;
  constraintsJson: string;
  contextSummary: string;
}

export interface IntentHandoffNode {
  id: string;
  hostname: string;
  spatialRefId: string | null;
  persistedSpatialRefId?: string | null;
}

/** Bounded so the scope stays far inside the intent payload limits. */
export const MAX_HANDOFF_ALERT_REFS = 5;

export function buildIntentHandoffFromNode(node: IntentHandoffNode, alerts: readonly BackendDeviceAlert[] = []): IntentHandoffPrefill {
  const refs = alerts.slice(0, MAX_HANDOFF_ALERT_REFS).map((alert) => ({
    alert_id: alert.alertId,
    alert_key: alert.alertKey,
    status: alert.status,
    severity: alert.severity,
    metric: alert.metric,
  }));
  const scope = {
    source: "digital_twin",
    device_id: node.id,
    spatial_ref_id: node.persistedSpatialRefId ?? null,
    backend_alerts: refs,
  };
  const constraints = {
    max_downtime: 0,
    preserve_connectivity: true,
    simulation_required: true,
    context_source: "digital_twin",
  };
  const active = alerts.filter((alert) => alert.status === "active").length;
  const acknowledged = alerts.length - active;
  const summary = [
    `device=${node.hostname}`,
    `backend_alerts=${active} active, ${acknowledged} acknowledged`,
    "action=operator choice",
  ].join(" | ");
  return {
    source: "digital-twin",
    action: null,
    scopeJson: JSON.stringify(scope),
    constraintsJson: JSON.stringify(constraints),
    contextSummary: summary,
  };
}

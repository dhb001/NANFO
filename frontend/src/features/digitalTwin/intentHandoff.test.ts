import { describe, expect, it } from "vitest";
import { intentHandoffState, readIntentHandoffState } from "@/features/intent/handoff";
import { MAX_HANDOFF_ALERT_REFS, buildIntentHandoffFromNode } from "./intentHandoff";
import { deriveDeviceAlertStates } from "./twinSeverity";

describe("Digital Twin -> Intent handoff", () => {
  const node = { id: "d1", hostname: "edge-1", spatialRefId: "session/only/ref", persistedSpatialRefId: "campus/b1/f1/r1/d1" };

  it("carries backend alert references only, never the visual heuristic or a policy", () => {
    const alerts = deriveDeviceAlertStates([{ alert_id: "a1", alert_key: "measured:k", status: "active", severity: "warning", updated_at: "2026-09-24T00:00:00Z",
      payload: { device_id: "d1", metric: "latency_ms", value: 130, unit: "ms" } }], []).get("d1")!.alerts;
    const handoff = buildIntentHandoffFromNode(node, alerts);
    expect(JSON.parse(handoff.scopeJson)).toEqual({
      source: "digital_twin", device_id: "d1", spatial_ref_id: "campus/b1/f1/r1/d1",
      backend_alerts: [{ alert_id: "a1", alert_key: "measured:k", status: "active", severity: "warning", metric: "latency_ms" }],
    });
    expect(handoff.scopeJson).not.toMatch(/policy|heuristic|congestion|score/);
    expect(handoff.action).toBeNull();
    expect(handoff.contextSummary).toBe("device=edge-1 | backend_alerts=1 active, 0 acknowledged | action=operator choice");
  });

  it("never embeds a session-only sidecar mapping and bounds alert references", () => {
    const alerts = Array.from({ length: 9 }, (_, index) => ({ key: `k${index}`, alertId: `a${index}`, alertKey: null, deviceId: "d1", status: "active" as const,
      severity: "warning", metric: "latency_ms", value: null, unit: null, breach: null, recover: null, origin: "live" as const }));
    const scope = JSON.parse(buildIntentHandoffFromNode({ ...node, persistedSpatialRefId: null }, alerts).scopeJson);
    expect(scope.spatial_ref_id).toBeNull();
    expect(scope.backend_alerts).toHaveLength(MAX_HANDOFF_ALERT_REFS);
  });

  it("travels as trusted router state (never in the URL) and carries no action", () => {
    const state = intentHandoffState(buildIntentHandoffFromNode(node));
    const reading = readIntentHandoffState(state);
    expect(reading).toMatchObject({ source: "digital-twin", action: null, untrusted: false, contextSummary: "device=edge-1 | backend_alerts=0 active, 0 acknowledged | action=operator choice" });
    expect(JSON.parse(reading!.constraintsJson)).toEqual({ max_downtime: 0, preserve_connectivity: true, simulation_required: true, context_source: "digital_twin" });
    expect(JSON.parse(reading!.scopeJson)).toEqual({ source: "digital_twin", device_id: "d1", spatial_ref_id: "campus/b1/f1/r1/d1", backend_alerts: [] });
  });
});

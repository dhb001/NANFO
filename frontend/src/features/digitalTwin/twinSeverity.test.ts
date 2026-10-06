import { describe, expect, it } from "vitest";
import {
  BACKEND_DETECTOR_RULES,
  activeAlertDeviceIds,
  alertDeviceId,
  deriveDeviceAlertStates,
  describeDeviceAlerts,
  detectorRuleFor,
  visualHeuristicLevel,
} from "./twinSeverity";

const record = (alertId: string, deviceId: string, status = "active", updatedAt = "2026-09-24T10:00:00Z", extra: Record<string, unknown> = {}) => ({
  alert_id: alertId, alert_key: `measured:${alertId}`, status, severity: "warning", updated_at: updatedAt,
  payload: { device_id: deviceId, metric: "latency_ms", value: 130, unit: "ms", rule: { breach: 100, recover: 70 }, ...extra },
});
const event = (type: string, payload: Record<string, unknown>, timestamp?: string) => ({ event_type: type, payload, timestamp });

describe("visual heuristic mirror of the backend detector", () => {
  it("matches detector.py defaults and requires the exact metric name and unit", () => {
    expect(BACKEND_DETECTOR_RULES).toEqual({
      link_utilization_percent: { id: "utilization", label: "Link utilization", unit: "%", breach: 85, recover: 70 },
      latency_ms: { id: "latency", label: "Latency", unit: "ms", breach: 100, recover: 70 },
      packet_loss_percent: { id: "loss", label: "Packet loss", unit: "%", breach: 2, recover: 1 },
      queue_backlog_packets: { id: "queue", label: "Queue backlog", unit: "packets", breach: 80, recover: 40 },
    });
    expect(detectorRuleFor("latency_ms", "s")).toBeNull();
    expect(detectorRuleFor("cpu_utilization_percent", "%")).toBeNull();
    expect(detectorRuleFor("toString", null)).toBeNull();
    expect(visualHeuristicLevel("queue_backlog_packets", "packets", 80)?.level).toBe("above_breach");
    expect(visualHeuristicLevel("queue_backlog_packets", "packets", 40)?.level).toBe("between_thresholds");
    expect(visualHeuristicLevel("queue_backlog_packets", "packets", 39.9)?.level).toBe("below_recovery");
    expect(visualHeuristicLevel("latency_ms", "ms", Number.NaN)).toBeNull();
    expect(visualHeuristicLevel("latency_ms", "ms", -1)).toBeNull();
  });
});

describe("backend alert state", () => {
  it("reads device references from measured payloads and nested scopes only", () => {
    expect(alertDeviceId({ device_id: " d1 " })).toBe("d1");
    expect(alertDeviceId({ scope: { device_id: "d2" } })).toBe("d2");
    expect(alertDeviceId({ metric: "latency_ms" })).toBeNull();
    expect(alertDeviceId(null)).toBeNull();
  });

  it("merges the REST snapshot with newer live lifecycle events per alert identity", () => {
    const states = deriveDeviceAlertStates(
      [record("a1", "d1"), record("a2", "d1", "active", "2026-09-24T10:00:00Z", { metric: "packet_loss_percent" }), record("a3", "d2"), record("a4", "d3")],
      [
        event("alert.resolved", { alert_id: "a1", device_id: "d1" }, "2026-09-24T10:05:00Z"),
        event("alert.acknowledged", { alert_id: "a3", device_id: "d2" }, "2026-09-24T10:05:00Z"),
        event("alert.resolved", { alert_id: "a4", device_id: "d3" }, "2026-09-24T09:00:00Z"),
        event("alert.generated", { alert_id: "a5", device_id: "d4", metric: "queue_backlog_packets", severity: "warning" }),
      ],
    );
    // Resolving a1 must not hide a2 on the same device.
    expect(states.get("d1")).toMatchObject({ status: "active", alerts: [expect.objectContaining({ alertId: "a2", metric: "packet_loss_percent" })] });
    expect(states.get("d2")?.status).toBe("acknowledged");
    // A live event older than the REST record does not override it.
    expect(states.get("d3")?.status).toBe("active");
    expect(states.get("d4")).toMatchObject({ status: "active", alerts: [expect.objectContaining({ origin: "live", metric: "queue_backlog_packets" })] });
    expect([...activeAlertDeviceIds(states)].sort()).toEqual(["d1", "d3", "d4"]);
    expect(states.get("d1")?.alerts[0]).toMatchObject({ breach: 100, recover: 70, severity: "warning", alertKey: "measured:a2" });
  });

  it("uses only the newest live event per alert and ignores unknown or device-less events", () => {
    const states = deriveDeviceAlertStates(undefined, [
      event("alert.resolved", { alert_id: "x", device_id: "d1" }),
      event("alert.generated", { alert_id: "x", device_id: "d1" }),
      event("alert.escalated", { alert_id: "y", device_id: "d2" }),
      event("alert.generated", { alert_id: "z", metric: "slo" }),
    ]);
    expect(states.size).toBe(0);
  });

  it("drops resolved REST records and devices outside the current topology", () => {
    const states = deriveDeviceAlertStates([record("a1", "d1", "resolved"), record("a2", "gone")], [], new Set(["d1"]));
    expect(states.size).toBe(0);
  });

  it("describes open alerts in text so severity is never colour-only", () => {
    const states = deriveDeviceAlertStates([record("a1", "d1"), record("a2", "d1", "acknowledged")], []);
    expect(describeDeviceAlerts(states.get("d1"))).toBe("1 active, 1 acknowledged backend alerts");
    expect(describeDeviceAlerts(undefined)).toBe("No open backend alerts");
  });
});

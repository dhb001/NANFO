import { describe, expect, it } from "vitest";
import { useLiveStore } from "@/features/realtime/store";

describe("realtime store", () => {
  it("deduplicates alerts by event_id and keeps latest first", () => {
    useLiveStore.setState({
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      sceneObjects: {},
      alerts: [],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "closed",
      digitalTwinStatus: "closed",
    });

    useLiveStore.getState().applyAlertDelta(
      {
        delta_type: "add",
        alert: {
          event_id: "evt-1",
          event_type: "alert.generated",
          source: "telemetry",
          payload: { severity: "high" },
        },
      },
      { correlation_id: "corr-1", timestamp: "2026-08-13T10:00:00Z" },
    );

    useLiveStore.getState().applyAlertDelta(
      {
        delta_type: "resolve",
        alert: {
          event_id: "evt-1",
          event_type: "alert.resolved",
          source: "telemetry",
          payload: { severity: "low" },
        },
      },
      { correlation_id: "corr-2", timestamp: "2026-08-13T10:01:00Z" },
    );

    useLiveStore.getState().applyAlertDelta(
      {
        delta_type: "add",
        alert: {
          event_id: "evt-2",
          event_type: "alert.generated",
          source: "telemetry",
          payload: { severity: "critical" },
        },
      },
      { correlation_id: "corr-3", timestamp: "2026-08-13T10:02:00Z" },
    );

    const alerts = useLiveStore.getState().alerts;
    expect(alerts).toHaveLength(2);
    expect(alerts[0].event_id).toBe("evt-2");
    expect(alerts[1].event_id).toBe("evt-1");
    expect(alerts[1].event_type).toBe("alert.resolved");
  });
});

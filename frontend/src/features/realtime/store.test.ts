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

  it("accepts acknowledged alert deltas", () => {
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
        delta_type: "ack",
        alert: {
          event_id: "evt-ack-1",
          event_type: "alert.acknowledged",
          source: "alert",
          payload: { status: "acknowledged" },
        },
      },
      { correlation_id: "corr-ack-1", timestamp: "2026-08-14T00:00:00Z" },
    );

    const alerts = useLiveStore.getState().alerts;
    expect(alerts).toHaveLength(1);
    expect(alerts[0].event_type).toBe("alert.acknowledged");
  });

  it("caps retained alerts at 200 and keeps newest-first deterministic ordering", () => {
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

    for (let index = 0; index < 250; index += 1) {
      useLiveStore.getState().applyAlertDelta(
        {
          delta_type: "add",
          alert: {
            event_id: `evt-${index}`,
            event_type: "alert.generated",
            source: "telemetry",
            payload: { severity: "high", sequence: index },
          },
        },
        { correlation_id: `corr-${index}`, timestamp: `2026-08-14T00:${String(index % 60).padStart(2, "0")}:00Z` },
      );
    }

    const afterBurst = useLiveStore.getState().alerts;
    expect(afterBurst).toHaveLength(200);
    expect(afterBurst[0].event_id).toBe("evt-249");
    expect(afterBurst[199].event_id).toBe("evt-50");

    useLiveStore.getState().applyAlertDelta(
      {
        delta_type: "resolve",
        alert: {
          event_id: "evt-100",
          event_type: "alert.resolved",
          source: "telemetry",
          payload: { severity: "low", sequence: 100 },
        },
      },
      { correlation_id: "corr-100b", timestamp: "2026-08-14T03:00:00Z" },
    );

    const afterUpdate = useLiveStore.getState().alerts;
    expect(afterUpdate).toHaveLength(200);
    expect(afterUpdate[0].event_id).toBe("evt-100");
    expect(afterUpdate[0].event_type).toBe("alert.resolved");
    expect(afterUpdate.filter((item) => item.event_id === "evt-100")).toHaveLength(1);
  });
});

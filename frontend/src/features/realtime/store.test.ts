import { describe, expect, it } from "vitest";
import { TELEMETRY_LIMITS, useLiveStore } from "@/features/realtime/store";

describe("realtime store", () => {
  const sample = { event_id: "sample", workspace_id: "w", network_id: "n", device_id: "quiet", metric: "cpu", value: 42, unit: "%", source: "plugin", observed_at: "2026-09-19T00:00:00Z", tags: {} };

  it("protects quiet resources from noisy metric identities and independent flow floods", () => {
    useLiveStore.getState().reset();
    const apply = useLiveStore.getState().applyTelemetryDelta;
    for (let i = 0; i < 40; i++) apply({ delta_type: "metric", metric: { ...sample, device_id: `quiet-${i}` } });
    for (let i = 0; i < 700; i++) {
      apply({ delta_type: "metric", metric: { ...sample, device_id: "noisy", metric: `metric-${i}`, tags: { port_no: i, run_id: `run-${i}` } } });
      apply({ delta_type: "metric", metric: { ...sample, device_id: "flows", metric: "flow_byte_count", event_id: `flow-${i}`, tags: { flow_index: i } } });
    }
    const state = useLiveStore.getState();
    const rows = Object.values(state.telemetryByDeviceMetric);
    expect(rows.filter((row) => row.device_id.startsWith("quiet-"))).toHaveLength(40);
    expect(rows.filter((row) => row.device_id === "noisy")).toHaveLength(TELEMETRY_LIMITS.metricsPerResource);
    expect(rows.filter((row) => row.metric.startsWith("flow_"))).toHaveLength(TELEMETRY_LIMITS.flowHistory);
    expect(state.telemetryKeysNewestFirst).toHaveLength(rows.length);
    expect(new Set(state.telemetryKeysNewestFirst).size).toBe(rows.length);
    expect(rows.some((row) => row.event_id === "flow-0")).toBe(false);
  });

  it("bounds resource cardinality and retains recent resources with separate scope identities", () => {
    useLiveStore.getState().reset();
    const apply = useLiveStore.getState().applyTelemetryDelta;
    for (let i = 0; i < 350; i++) {
      for (let metric = 0; metric < 2; metric++) apply({ delta_type: "metric", metric: { ...sample, device_id: `d-${i}`, metric: `m-${metric}` } });
    }
    const rows = Object.values(useLiveStore.getState().telemetryByDeviceMetric);
    expect(new Set(rows.map((row) => row.device_id)).size).toBe(TELEMETRY_LIMITS.resources);
    expect(rows).toHaveLength(TELEMETRY_LIMITS.resources * 2);
    expect(rows.some((row) => row.device_id === "d-0")).toBe(false);
    expect(rows.filter((row) => row.device_id === "d-349")).toHaveLength(2);
    useLiveStore.getState().reset();
    for (const scope of [{ workspace_id: "w", network_id: "n" }, { workspace_id: "w2", network_id: "n" }, { workspace_id: "w", network_id: "n2" }]) {
      apply({ delta_type: "metric", metric: { ...sample, ...scope } });
    }
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toHaveLength(3);
    useLiveStore.getState().reset();
    expect(useLiveStore.getState().telemetryByDeviceMetric).toEqual({});
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toEqual([]);
  });

  it("rejects stale, duplicate and malformed latest observations without changing retention order", () => {
    useLiveStore.getState().reset();
    const apply = useLiveStore.getState().applyTelemetryDelta;
    apply({ delta_type: "metric", metric: sample });
    const before = useLiveStore.getState();
    for (const invalid of [{ value: Infinity }, { value: NaN }, { observed_at: "invalid" }, { observed_at: "2026-09-18T00:00:00Z" }, { value: 1 }, { tags: [] }]) {
      apply({ delta_type: "metric", metric: { ...sample, ...invalid } as typeof sample });
    }
    expect(useLiveStore.getState()).toBe(before);
    apply({ delta_type: "metric", metric: { ...sample, observed_at: "2026-09-19T00:01:00Z", value: 50 } });
    expect(Object.values(useLiveStore.getState().telemetryByDeviceMetric).map((row) => row.value)).toEqual([50]);
  });

  it("retains snapshot-local flow entries with repeated cookie/index across snapshots", () => {
    useLiveStore.getState().reset();
    const metric = { event_id: "flow-a", workspace_id: "w", network_id: "n", device_id: "d", metric: "flow_byte_count", unit: "bytes", source: "emulation", observed_at: "2026-09-10T00:00:00Z", value: 100, tags: { table_id: 0, cookie: "0", priority: 100, flow_index: 1 } };
    const apply = useLiveStore.getState().applyTelemetryDelta;
    apply({ delta_type: "metric", metric });
    apply({ delta_type: "metric", metric: { ...metric, event_id: "flow-b", value: 200 } });
    apply({ delta_type: "metric", metric: { ...metric, event_id: "flow-c", observed_at: "2026-09-10T00:01:00Z", value: 5 } });
    apply({ delta_type: "metric", metric });
    expect(Object.values(useLiveStore.getState().telemetryByDeviceMetric).map((row) => row.value)).toEqual([100, 200, 5]);
  });
  it("keeps removal tombstones until a later complete snapshot confirms absence, rejecting old deltas and scopes", () => {
    useLiveStore.getState().reset();
    const { epoch, reconcileTopologySnapshot, applyTopologyDelta } = useLiveStore.getState();
    applyTopologyDelta({ delta_type: "remove", node: { device_id: "removed" } }, "2026-09-10T00:01:00Z");
    applyTopologyDelta({ delta_type: "add", node: { device_id: "removed" } }, "2026-09-10T00:00:00Z");
    expect(useLiveStore.getState().topologyByDeviceId.removed).toBeUndefined();
    reconcileTopologySnapshot([], epoch, 0);
    expect(useLiveStore.getState().topologyTombstones.removed).toBe(1);
    reconcileTopologySnapshot(["removed"], epoch, 1);
    expect(useLiveStore.getState().topologyTombstones.removed).toBe(1);
    reconcileTopologySnapshot([], epoch - 1, 1);
    expect(useLiveStore.getState().topologyTombstones.removed).toBe(1);
    reconcileTopologySnapshot([], epoch, 1);
    expect(useLiveStore.getState().topologyTombstones.removed).toBeUndefined();
    applyTopologyDelta({ delta_type: "add", node: { device_id: "removed" } }, "2026-09-10T00:00:00Z");
    expect(useLiveStore.getState().topologyByDeviceId.removed).toBeUndefined();
    applyTopologyDelta({ delta_type: "add", node: { device_id: "removed" } }, "2026-09-10T00:02:00Z");
    expect(useLiveStore.getState().topologyByDeviceId.removed).toBeDefined();
  });

  it("retains independent simulation IDs and latest timestamps despite constant producer IDs", () => {
    useLiveStore.getState().reset();
    const apply = useLiveStore.getState().applyDigitalTwinDelta;
    const object = { id: "simulation-state", object_type: "simulation_state", simulation_id: "a", status: "completed" };
    apply({ delta_type: "update", scene_object: object }, "2026-09-10T00:02:00Z");
    apply({ delta_type: "update", scene_object: { ...object, simulation_id: "b" } }, "2026-09-10T00:01:00Z");
    apply({ delta_type: "update", scene_object: { ...object, status: "queued" } }, "2026-09-10T00:01:00Z");
    expect(useLiveStore.getState().sceneObjectIdsNewestFirst).toHaveLength(2);
    expect(useLiveStore.getState().sceneObjects["simulation:a"]).toMatchObject({ id: "simulation:a", status: "completed" });
    expect(useLiveStore.getState().sceneObjectLastSeen["simulation:a"]).toBe(Date.parse("2026-09-10T00:02:00Z"));
  });

  it("uses observed_at ordering within run, port and peer identity", () => {
    useLiveStore.getState().reset();
    const metric = { event_id: "m", workspace_id: "w", network_id: "n", device_id: "d", metric: "cpu", value: 90, unit: "%", source: "plugin", observed_at: "2026-09-10T00:02:00Z", tags: { run_id: "run-a", port_no: 1, peer_host: "a" } };
    const apply = useLiveStore.getState().applyTelemetryDelta;
    apply({ delta_type: "metric", metric });
    apply({ delta_type: "metric", metric: { ...metric, value: 1, observed_at: "2026-09-10T00:01:00Z" } });
    for (const tags of [{ ...metric.tags, run_id: "run-b" }, { ...metric.tags, port_no: 2 }, { ...metric.tags, peer_host: "b" }]) apply({ delta_type: "metric", metric: { ...metric, tags } });
    expect(Object.values(useLiveStore.getState().telemetryByDeviceMetric)).toHaveLength(4);
    expect(Object.values(useLiveStore.getState().telemetryByDeviceMetric).every((value) => value.value === 90)).toBe(true);
  });
  it("deduplicates alerts by event_id and keeps latest first", () => {
    useLiveStore.setState({
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
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
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
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
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
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

  it("caps retained telemetry metrics at 300 with newest-first key ordering", () => {
    useLiveStore.setState({
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
      alerts: [],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "closed",
      digitalTwinStatus: "closed",
    });

    for (let index = 0; index < 360; index += 1) {
      useLiveStore.getState().applyTelemetryDelta({
        delta_type: "metric",
        metric: {
          event_id: `evt-${index}`,
          device_id: `device-${index}`,
          network_id: "network-1",
          workspace_id: "workspace-1",
          metric: "cpu_usage",
          value: index,
          unit: "%",
          observed_at: `2026-08-15T00:${String(index % 60).padStart(2, "0")}:00Z`,
          source: "runtime",
          tags: {},
        },
      });
    }

    const state = useLiveStore.getState();
    const keys = Object.keys(state.telemetryByDeviceMetric);
    expect(keys).toHaveLength(300);
    expect(state.telemetryKeysNewestFirst).toHaveLength(300);
    expect(state.telemetryByDeviceMetric[state.telemetryKeysNewestFirst[0]].device_id).toBe("device-359");
    expect(state.telemetryByDeviceMetric[state.telemetryKeysNewestFirst[299]].device_id).toBe("device-60");
  });

  it("retains separate ports for the same device and metric", () => {
    useLiveStore.getState().reset();
    for (const port of [1, 2, 1]) {
      useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: {
        event_id: `port-${port}`, device_id: "switch", network_id: "network", workspace_id: "workspace",
        metric: "queue_backlog_bytes", value: port * 100, unit: "bytes", source: "emulation",
        observed_at: "2026-09-08T00:00:00Z", tags: { port_no: port, synthetic: false, execution_mode: "emulation" },
      } });
    }
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toHaveLength(2);
    expect(Object.values(useLiveStore.getState().telemetryByDeviceMetric).map((metric) => metric.tags.port_no).sort()).toEqual([1, 2]);
    useLiveStore.getState().reset();
  });

  it("caps retained scene objects at 300 with newest-first object ordering", () => {
    useLiveStore.setState({
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
      alerts: [],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "closed",
      digitalTwinStatus: "closed",
    });

    for (let index = 0; index < 360; index += 1) {
      useLiveStore.getState().applyDigitalTwinDelta({
        delta_type: "update",
        scene_object: {
          id: `scene-${index}`,
          object_type: "simulation_state",
          status: index % 2 === 0 ? "running" : "completed",
        },
      });
    }

    const state = useLiveStore.getState();
    const ids = Object.keys(state.sceneObjects);
    expect(ids).toHaveLength(300);
    expect(state.sceneObjectIdsNewestFirst).toHaveLength(300);
    expect(state.sceneObjectIdsNewestFirst[0]).toBe("scene-359");
    expect(state.sceneObjectIdsNewestFirst[299]).toBe("scene-60");
  });
});

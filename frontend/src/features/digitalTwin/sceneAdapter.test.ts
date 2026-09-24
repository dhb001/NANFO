import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildTwinSceneModel,
  buildTwinTopology,
  deriveDeterministicPlacement,
  deriveDeviceCongestion,
  parseSpatialRefPath,
} from "@/features/digitalTwin/sceneAdapter";
import { BACKEND_DETECTOR_RULES, VISUAL_HEURISTIC_ID } from "@/features/digitalTwin/twinSeverity";

describe("digital twin scene adapter", () => {
  beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-18T10:01:00Z")));
  afterEach(() => vi.restoreAllMocks());
  it("parses hierarchical spatial_ref_id paths", () => {
    const parsed = parseSpatialRefPath("campus-a/building-1/floor-2/rack-3/device-9");
    expect(parsed).not.toBeNull();
    expect(parsed?.campus).toBe("campus-a");
    expect(parsed?.building).toBe("building-1");
    expect(parsed?.floor).toBe("floor-2");
    expect(parsed?.rack).toBe("rack-3");
    expect(parsed?.device).toBe("device-9");
  });

  it("returns null for missing or blank spatial_ref_id", () => {
    expect(parseSpatialRefPath(null)).toBeNull();
    expect(parseSpatialRefPath("   ")).toBeNull();
  });

  it("derives deterministic placement from spatial_ref_id", () => {
    const first = deriveDeterministicPlacement("campus-a/building-1/floor-2/rack-3/device-9", "fallback-1");
    const second = deriveDeterministicPlacement("campus-a/building-1/floor-2/rack-3/device-9", "fallback-2");

    expect(first.mode).toBe("spatial_ref");
    expect(second.mode).toBe("spatial_ref");
    expect(first.x).toBeCloseTo(second.x, 10);
    expect(first.y).toBeCloseTo(second.y, 10);
    expect(first.z).toBeCloseTo(second.z, 10);
  });

  it("keeps hash fallback deterministic when spatial_ref_id is absent", () => {
    const first = deriveDeterministicPlacement(null, "device-1");
    const second = deriveDeterministicPlacement(undefined, "device-1");
    expect(first.mode).toBe("hash_fallback");
    expect(first.x).toBeCloseTo(second.x, 10);
    expect(first.y).toBeCloseTo(second.y, 10);
    expect(first.z).toBeCloseTo(second.z, 10);
  });

  const metric = (name: string, value: number, unit: string | null, extra: Record<string, unknown> = {}) => ({
    event_id: `evt-${name}-${value}`,
    device_id: "device-1",
    network_id: "network-1",
    workspace_id: "workspace-1",
    metric: name,
    value,
    unit,
    observed_at: "2026-08-18T10:00:30Z",
    source: "emulation",
    tags: {},
    ...extra,
  });

  it("mirrors the backend detector default thresholds and phase semantics exactly", () => {
    // backend/app/modules/alert/detector.py: breach >= breach, recovery < recover.
    const cases: Array<[string, string, number, number]> = [
      ["link_utilization_percent", "%", 85, 70],
      ["latency_ms", "ms", 100, 70],
      ["packet_loss_percent", "%", 2, 1],
      ["queue_backlog_packets", "packets", 80, 40],
    ];
    for (const [name, unit, breach, recover] of cases) {
      expect(BACKEND_DETECTOR_RULES[name]).toMatchObject({ unit, breach, recover });
      expect(deriveDeviceCongestion([metric(name, breach, unit)]).severity).toBe("high");
      expect(deriveDeviceCongestion([metric(name, breach - 0.001, unit)]).severity).toBe("medium");
      expect(deriveDeviceCongestion([metric(name, recover, unit)]).severity).toBe("medium");
      expect(deriveDeviceCongestion([metric(name, recover - 0.001, unit)]).severity).toBe("low");
      expect(deriveDeviceCongestion([metric(name, breach * 2, "other-unit")]).severity).toBe("neutral");
    }
    expect(Object.keys(BACKEND_DETECTOR_RULES).sort()).toEqual(["latency_ms", "link_utilization_percent", "packet_loss_percent", "queue_backlog_packets"]);
  });

  it("derives neutral congestion when no detector-covered metrics exist", () => {
    const congestion = deriveDeviceCongestion([metric("temperature", 56, "c"), metric("cpu_usage", 99, "%")]);

    expect(congestion.severity).toBe("neutral");
    expect(congestion.metrics).toHaveLength(0);
    expect(congestion.heuristic).toBe(VISUAL_HEURISTIC_ID);
    expect(congestion.primaryMetric).toBeNull();
  });

  it("colours from detector-covered metrics only and exposes the mirrored rule", () => {
    const congestion = deriveDeviceCongestion([metric("cpu_usage", 82, "%"), { ...metric("latency_ms", 130, "ms"), observed_at: "2026-08-18T10:00:50Z" }]);

    expect(congestion.severity).toBe("high");
    expect(congestion.primaryMetric).toBe("latency_ms");
    expect(congestion.metrics).toHaveLength(1);
    expect(congestion.metrics[0]).toMatchObject({ level: "above_breach", rule: { id: "latency", breach: 100, recover: 70 } });
    expect(congestion).not.toHaveProperty("policyVersion");
    expect(congestion).not.toHaveProperty("score");
  });

  it("ignores invented policy hints and substring metric names", () => {
    const congestion = deriveDeviceCongestion([
      metric("custom-score", 50, "%", { tags: { congestion_policy: "packet_loss_percent" } }),
      metric("packet_loss", 50, "%"),
      metric("interface_latency_ms_p99", 500, "ms"),
      metric("packet_loss_percent", 0.5, "%"),
    ]);

    expect(congestion.severity).toBe("low");
    expect(congestion.metrics.map((item) => item.metric)).toEqual(["packet_loss_percent"]);
  });

  it("orders current samples before stale ones and never colours from stale samples", () => {
    const stale = { ...metric("packet_loss_percent", 9, "%"), observed_at: "2026-08-18T09:00:00Z" };
    const current = metric("latency_ms", 80, "ms");
    const congestion = deriveDeviceCongestion([stale, current]);
    expect(congestion.severity).toBe("medium");
    expect(congestion.metrics.map((item) => [item.metric, item.stale])).toEqual([["latency_ms", false], ["packet_loss_percent", true]]);
    expect(deriveDeviceCongestion([stale]).severity).toBe("neutral");
    expect(deriveDeviceCongestion([{ ...current, tags: { stale: true } }]).severity).toBe("neutral");
  });

  it("keeps persisted and session-only spatial references separate", () => {
    const topology = buildTwinTopology({
      baseNodes: [
        { device_id: "a", hostname: "a", device_type: "switch", status: "active", spatial_ref_id: " campus/b1/f1/r1/a " },
        { device_id: "b", hostname: "b", device_type: "switch", status: "active", spatial_ref_id: null },
      ],
      baseEdges: [], liveNodesByDeviceId: {}, importedSpatialRefByDeviceId: { b: "campus/b2/f1/r1/b" },
    });
    expect(topology.nodeById.a).toMatchObject({ spatialRefId: "campus/b1/f1/r1/a", persistedSpatialRefId: "campus/b1/f1/r1/a" });
    expect(topology.nodeById.b).toMatchObject({ spatialRefId: "campus/b2/f1/r1/b", persistedSpatialRefId: null });
    expect(topology.nodeById.a).not.toHaveProperty("congestion");
  });

  it("builds deterministic scene model with overlays", () => {
    const model = buildTwinSceneModel({
      baseNodes: [
        {
          device_id: "device-1",
          hostname: "edge-1",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/building-1/floor-1/rack-1/device-1",
        },
      ],
      baseEdges: [
        {
          source_id: "device-1",
          target_id: "device-1",
          edge_type: "connected_to",
          metadata: {},
        },
      ],
      liveNodesByDeviceId: {},
      telemetryByDeviceMetric: {
        "device-1:link_utilization_percent": {
          event_id: "evt-1",
          device_id: "device-1",
          network_id: "network-1",
          workspace_id: "workspace-1",
          metric: "link_utilization_percent",
          value: 35,
          unit: "%",
          observed_at: "2026-08-18T10:00:00Z",
          source: "runtime",
          tags: {},
        },
      },
      telemetryKeysNewestFirst: ["device-1:link_utilization_percent"],
      sceneObjects: {
        "intent-1": {
          id: "intent-1",
          object_type: "intent_state",
          status: "validated",
          changed_fields: {
            spatial_ref_id: "campus-a/building-1/floor-1/rack-2/intent-1",
          },
        },
        "simulation-1": {
          id: "simulation-1",
          object_type: "simulation_state",
          status: "running",
        },
      },
      sceneObjectIdsNewestFirst: ["intent-1", "simulation-1"],
    });

    expect(model.nodes).toHaveLength(1);
    expect(model.links).toHaveLength(1);
    expect(model.overlays).toHaveLength(2);
    expect(model.overlays[0]?.objectType).toBe("simulation_state");
    expect(model.overlays[1]?.objectType).toBe("intent_state");
    expect(model.nodeById["device-1"]?.congestion.severity).toBe("low");
  });
});

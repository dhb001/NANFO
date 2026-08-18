import { describe, expect, it } from "vitest";
import {
  CONGESTION_POLICY_VERSION,
  buildTwinSceneModel,
  deriveDeterministicPlacement,
  deriveDeviceCongestion,
  mapCongestionSeverity,
  parseSpatialRefPath,
} from "@/features/digitalTwin/sceneAdapter";

describe("digital twin scene adapter", () => {
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

  it("maps congestion severity using deterministic thresholds", () => {
    expect(mapCongestionSeverity(null)).toBe("neutral");
    expect(mapCongestionSeverity(0.2)).toBe("low");
    expect(mapCongestionSeverity(0.45)).toBe("medium");
    expect(mapCongestionSeverity(0.88)).toBe("high");
  });

  it("derives neutral congestion when no recognized metrics exist", () => {
    const congestion = deriveDeviceCongestion([
      {
        event_id: "evt-1",
        device_id: "device-1",
        network_id: "network-1",
        workspace_id: "workspace-1",
        metric: "temperature",
        value: 56,
        unit: "c",
        observed_at: "2026-08-18T10:00:00Z",
        source: "runtime",
        tags: {},
      },
    ]);

    expect(congestion.severity).toBe("neutral");
    expect(congestion.score).toBeNull();
    expect(congestion.metrics).toHaveLength(0);
    expect(congestion.policyVersion).toBe(CONGESTION_POLICY_VERSION);
    expect(congestion.primaryPolicyId).toBeNull();
  });

  it("derives high congestion from recognized telemetry metrics", () => {
    const congestion = deriveDeviceCongestion([
      {
        event_id: "evt-1",
        device_id: "device-1",
        network_id: "network-1",
        workspace_id: "workspace-1",
        metric: "cpu_usage",
        value: 82,
        unit: "%",
        observed_at: "2026-08-18T10:00:00Z",
        source: "runtime",
        tags: {},
      },
      {
        event_id: "evt-2",
        device_id: "device-1",
        network_id: "network-1",
        workspace_id: "workspace-1",
        metric: "latency_ms",
        value: 45,
        unit: "ms",
        observed_at: "2026-08-18T10:01:00Z",
        source: "runtime",
        tags: {},
      },
    ]);

    expect(congestion.severity).toBe("high");
    expect(congestion.score).not.toBeNull();
    expect(congestion.metrics.length).toBeGreaterThan(0);
    expect(congestion.primaryPolicyId).toBe("cpu_utilization_percent");
  });

  it("uses policy priority and tag hint with deterministic tie-breaking", () => {
    const congestion = deriveDeviceCongestion([
      {
        event_id: "evt-1",
        device_id: "device-1",
        network_id: "network-1",
        workspace_id: "workspace-1",
        metric: "custom-score",
        value: 2,
        unit: "%",
        observed_at: "2026-08-18T10:00:00Z",
        source: "runtime",
        tags: { congestion_policy: "packet_loss_percent" },
      },
      {
        event_id: "evt-2",
        device_id: "device-1",
        network_id: "network-1",
        workspace_id: "workspace-1",
        metric: "cpu_usage",
        value: 95,
        unit: "%",
        observed_at: "2026-08-18T10:01:00Z",
        source: "runtime",
        tags: {},
      },
    ]);

    expect(congestion.severity).toBe("high");
    expect(congestion.primaryPolicyId).toBe("cpu_utilization_percent");
    expect(congestion.metrics[0]?.policyId).toBe("cpu_utilization_percent");
    expect(congestion.metrics[1]?.policyId).toBe("packet_loss_percent");
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
        "device-1:cpu_usage": {
          event_id: "evt-1",
          device_id: "device-1",
          network_id: "network-1",
          workspace_id: "workspace-1",
          metric: "cpu_usage",
          value: 35,
          unit: "%",
          observed_at: "2026-08-18T10:00:00Z",
          source: "runtime",
          tags: {},
        },
      },
      telemetryKeysNewestFirst: ["device-1:cpu_usage"],
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

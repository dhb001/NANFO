import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { useTwinLinks, useTwinNodes, useTwinSceneModel } from "@/features/digitalTwin/hooks";
import { useLiveStore } from "@/features/realtime/store";

describe("digital twin hooks", () => {
  it("merges base topology and live deltas into node list", () => {
    useLiveStore.setState({
      topologyByDeviceId: {
        "device-2": {
          device_id: "device-2",
          hostname: "access-2-live",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/rack-2",
        },
      },
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

    const { result } = renderHook(() =>
      useTwinNodes([
        {
          device_id: "device-1",
          hostname: "core-1",
          device_type: "router",
          status: "active",
          spatial_ref_id: null,
        },
      ]),
    );

    expect(result.current).toHaveLength(2);
    expect(result.current.find((node) => node.id === "device-1")?.hostname).toBe("core-1");
    expect(result.current.find((node) => node.id === "device-2")?.hostname).toBe("access-2-live");
    expect(result.current.every((node) => typeof node.congestion.severity === "string")).toBe(true);
  });

  it("builds links only when source and target nodes exist", () => {
    const nodes = [
      {
        id: "a",
        hostname: "A",
        type: "router",
        status: "active",
        x: 0,
        y: 0,
        z: 0,
        spatialRefId: null,
        congestion: { severity: "neutral", score: null, metrics: [] },
      },
      {
        id: "b",
        hostname: "B",
        type: "switch",
        status: "active",
        x: 1,
        y: 0,
        z: 1,
        spatialRefId: null,
        congestion: { severity: "neutral", score: null, metrics: [] },
      },
    ];

    const { result } = renderHook(() =>
      useTwinLinks(nodes, [
        { source_id: "a", target_id: "b", edge_type: "connected_to", metadata: {} },
        { source_id: "a", target_id: "missing", edge_type: "connected_to", metadata: {} },
      ]),
    );

    expect(result.current).toHaveLength(1);
    expect(result.current[0].edgeType).toBe("connected_to");
  });

  it("builds overlays from live simulation and intent scene objects", () => {
    useLiveStore.setState({
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      sceneObjects: {
        "simulation-state": {
          id: "simulation-state",
          object_type: "simulation_state",
          status: "queued",
          spatial_ref_id: "campus-a/building-1/floor-2/rack-3/sim-1",
        },
        "intent-state": {
          id: "intent-state",
          object_type: "intent_state",
          status: "validated",
          changed_fields: {
            spatial_ref_id: "campus-a/building-1/floor-1/rack-9/intent-1",
          },
        },
      },
      sceneObjectIdsNewestFirst: ["intent-state", "simulation-state"],
      alerts: [],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "closed",
      digitalTwinStatus: "closed",
    });

    const { result } = renderHook(() => useTwinSceneModel([], []));

    expect(result.current.overlays).toHaveLength(2);
    expect(result.current.overlays[0].id).toBe("intent-state");
    expect(result.current.overlays[0].spatialRefId).toBe("campus-a/building-1/floor-1/rack-9/intent-1");
    expect(result.current.overlays[1].id).toBe("simulation-state");
  });
});

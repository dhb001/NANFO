import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useTwinLinks, useTwinNodes, useTwinSceneModel } from "@/features/digitalTwin/hooks";
import { useLiveStore } from "@/features/realtime/store";
import { buildTwinSceneModel, type TwinNode } from "@/features/digitalTwin/sceneAdapter";
import { topologyEdgeIdentity } from "@/features/topology/edgeIdentity";

describe("digital twin hooks", () => {
  it("suppresses removed REST nodes and expires congestion on the clock without another push", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-10T00:00:00Z"));
    useLiveStore.getState().reset();
    const base = [{ device_id: "d", hostname: "device", device_type: "switch", status: "active", spatial_ref_id: null }];
    useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: {
      event_id: "m", workspace_id: "w", network_id: "n", device_id: "d", metric: "cpu", value: 90, unit: "%", source: "plugin", observed_at: new Date().toISOString(), tags: { run_id: "r", port_no: 1 },
    } });
    const { result, unmount } = renderHook(() => useTwinSceneModel(base));
    expect(result.current.nodes[0].congestion.severity).toBe("high");
    act(() => vi.advanceTimersByTime(65_000));
    expect(result.current.nodes[0].congestion.severity).toBe("neutral");
    expect(result.current.nodes[0].congestion.metrics[0]).toMatchObject({ stale: true, value: 90, tags: { run_id: "r", port_no: 1 } });
    act(() => useLiveStore.getState().applyTopologyDelta({ delta_type: "remove", node: { device_id: "d" } }));
    expect(result.current.nodes).toHaveLength(0);
    unmount();
    useLiveStore.getState().reset();
    vi.useRealTimers();
  });
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
    const nodes: TwinNode[] = [
      {
        id: "a",
        hostname: "A",
        type: "router",
        status: "active",
        x: 0,
        y: 0,
        z: 0,
        spatialRefId: null,
        congestion: {
          severity: "neutral",
          score: null,
          metrics: [],
          policyVersion: "v2.0.0",
          primaryPolicyId: null,
        },
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
        congestion: {
          severity: "neutral",
          score: null,
          metrics: [],
          policyVersion: "v2.0.0",
          primaryPolicyId: null,
        },
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

  it("preserves parallel observed link IDs and metadata in both Twin builders", () => {
    const base = { source_id: "a", target_id: "b", edge_type: "connected_to" };
    const metadata = { observation_owner: "lab-a", edge_key: "link", source_port: 1, target_port: 2 };
    const distinct = [
      { ...base, metadata },
      { ...base, metadata: { ...metadata, source_port: 3 } },
      { ...base, metadata: { ...metadata, target_port: 4 } },
      { ...base, metadata: { ...metadata, observation_owner: "lab-b" } },
      { ...base, metadata: { ...metadata, edge_key: "parallel" } },
      { ...base, metadata: { synthetic: true } },
      { ...base, metadata: { synthetic: false } },
    ];
    const edges = [...distinct, distinct[5]];
    const scene = buildTwinSceneModel({
      baseNodes: ["a", "b"].map((id) => ({ device_id: id, hostname: id, device_type: "switch", status: "active", spatial_ref_id: null })),
      baseEdges: edges, liveNodesByDeviceId: {}, telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [], sceneObjects: {}, sceneObjectIdsNewestFirst: [],
    });
    const { result } = renderHook(() => useTwinLinks(scene.nodes, edges));
    for (const links of [scene.links, result.current]) {
      expect(links).toHaveLength(7);
      expect(new Set(links.map((link) => link.id)).size).toBe(7);
      for (const edge of distinct) {
        expect(links.find((link) => link.id === topologyEdgeIdentity(edge))?.metadata).toEqual(edge.metadata);
      }
    }
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
    expect(result.current.overlays[0].id).toBe("simulation-state");
    expect(result.current.overlays[1].id).toBe("intent-state");
    expect(result.current.overlays[1].spatialRefId).toBe("campus-a/building-1/floor-1/rack-9/intent-1");
  });
});

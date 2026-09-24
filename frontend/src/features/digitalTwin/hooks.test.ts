import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useTwinSceneModel } from "@/features/digitalTwin/hooks";
import { useLiveStore } from "@/features/realtime/store";
import { buildTwinSceneModel } from "@/features/digitalTwin/sceneAdapter";
import { topologyEdgeIdentity } from "@/features/topology/edgeIdentity";

describe("digital twin hooks", () => {
  it("passes all store-retained resources through beyond 240 keys, even behind noisy flow history", () => {
    useLiveStore.getState().reset();
    const now = new Date().toISOString();
    const metric = { event_id: "m", workspace_id: "w", network_id: "n", device_id: "quiet", metric: "packet_loss_percent", value: 5, unit: "%", source: "plugin", observed_at: now, tags: {} };
    useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric });
    for (let i = 0; i < 15; i++) useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: { ...metric, metric: `temperature${i}`, unit: "C", event_id: `extra${i}` } });
    const nodes = [{ device_id: "quiet", hostname: "quiet", device_type: "switch", status: "active", spatial_ref_id: null }];
    for (let i = 0; i < 270; i++) {
      const id = `d${i}`;
      nodes.push({ ...nodes[0], device_id: id, hostname: id });
      useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: { ...metric, device_id: id, event_id: id } });
    }
    for (let i = 0; i < 300; i++) useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: { ...metric, metric: "flow_bytes", event_id: `flow${i}` } });
    const { result, unmount } = renderHook(() => useTwinSceneModel(nodes));
    expect(result.current.nodes).toHaveLength(271);
    expect(result.current.nodes.every((node) => node.congestion.severity === "high")).toBe(true);
    expect(result.current.nodeById.quiet.congestion.metrics).toHaveLength(1);
    unmount(); useLiveStore.getState().reset();
  });
  it("suppresses removed REST nodes and expires congestion on the clock without another push", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-10T00:00:00Z"));
    useLiveStore.getState().reset();
    const base = [{ device_id: "d", hostname: "device", device_type: "switch", status: "active", spatial_ref_id: null }];
    useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: {
      event_id: "m", workspace_id: "w", network_id: "n", device_id: "d", metric: "link_utilization_percent", value: 90, unit: "%", source: "plugin", observed_at: new Date().toISOString(), tags: { run_id: "r", port_no: 1 },
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

    const baseNodes = [
      {
        device_id: "device-1",
        hostname: "core-1",
        device_type: "router",
        status: "active",
        spatial_ref_id: null,
      },
    ];
    const { result } = renderHook(() => useTwinSceneModel(baseNodes));

    expect(result.current.nodes).toHaveLength(2);
    expect(result.current.nodes.find((node) => node.id === "device-1")?.hostname).toBe("core-1");
    expect(result.current.nodes.find((node) => node.id === "device-2")?.hostname).toBe("access-2-live");
    expect(result.current.nodes.every((node) => typeof node.congestion.severity === "string")).toBe(true);
  });

  it("builds links only when source and target nodes exist", () => {
    const scene = buildTwinSceneModel({
      baseNodes: [
        { device_id: "a", hostname: "A", device_type: "router", status: "active", spatial_ref_id: null },
        { device_id: "b", hostname: "B", device_type: "switch", status: "active", spatial_ref_id: null },
      ],
      baseEdges: [
        { source_id: "a", target_id: "b", edge_type: "connected_to", metadata: {} },
        { source_id: "a", target_id: "missing", edge_type: "connected_to", metadata: {} },
      ],
      liveNodesByDeviceId: {}, telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [], sceneObjects: {}, sceneObjectIdsNewestFirst: [],
    });

    expect(scene.links).toHaveLength(1);
    expect(scene.links[0].edgeType).toBe("connected_to");
  });

  it("preserves parallel observed link IDs and metadata in the Twin builder", () => {
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
    const links = scene.links;
    expect(links).toHaveLength(7);
    expect(new Set(links.map((link) => link.id)).size).toBe(7);
    for (const edge of distinct) {
      expect(links.find((link) => link.id === topologyEdgeIdentity(edge))?.metadata).toEqual(edge.metadata);
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

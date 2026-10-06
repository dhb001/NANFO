import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useTwinLiveCongestion, useTwinOverlays, useTwinTopology, type FrameScheduler } from "@/features/digitalTwin/hooks";
import { useLiveStore } from "@/features/realtime/store";
import { buildTwinSceneModel } from "@/features/digitalTwin/sceneAdapter";
import { topologyEdgeIdentity } from "@/features/topology/edgeIdentity";

/** Deterministic frame scheduler: frames run only when the test flushes them. */
function manualScheduler() {
  const queue = new Map<number, () => void>();
  let next = 1;
  const scheduler: FrameScheduler & { flush: () => void; pending: () => number; requests: number } = {
    requests: 0,
    request: (callback) => { scheduler.requests += 1; const handle = next++; queue.set(handle, callback); return handle; },
    cancel: (handle) => { queue.delete(handle); },
    flush: () => { const callbacks = [...queue.values()]; queue.clear(); callbacks.forEach((callback) => callback()); },
    pending: () => queue.size,
  };
  return scheduler;
}

const telemetry = (deviceId: string, metric = "latency_ms", value = 150, unit = "ms", extra: Record<string, unknown> = {}) => ({
  event_id: `${deviceId}-${metric}-${value}`, workspace_id: "w", network_id: "n", device_id: deviceId, metric, value, unit, source: "plugin",
  observed_at: new Date().toISOString(), tags: {}, ...extra,
});

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
    const topology = renderHook(() => useTwinTopology(nodes));
    const congestion = renderHook(() => useTwinLiveCongestion(manualScheduler()));
    expect(topology.result.current.nodes).toHaveLength(271);
    expect(topology.result.current.nodes.every((node) => congestion.result.current[node.id]?.severity === "high")).toBe(true);
    expect(congestion.result.current.quiet.metrics).toHaveLength(1);
    topology.unmount(); congestion.unmount(); useLiveStore.getState().reset();
  });

  it("suppresses removed REST nodes and expires congestion on the clock without another push", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-10T00:00:00Z"));
    useLiveStore.getState().reset();
    const base = [{ device_id: "d", hostname: "device", device_type: "switch", status: "active", spatial_ref_id: null }];
    useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: telemetry("d", "link_utilization_percent", 90, "%", { tags: { run_id: "r", port_no: 1 } }) });
    const scheduler = manualScheduler();
    const topology = renderHook(() => useTwinTopology(base));
    const congestion = renderHook(() => useTwinLiveCongestion(scheduler));
    expect(congestion.result.current.d.severity).toBe("high");
    act(() => { vi.advanceTimersByTime(65_000); scheduler.flush(); });
    expect(congestion.result.current.d.severity).toBe("neutral");
    expect(congestion.result.current.d.metrics[0]).toMatchObject({ stale: true, value: 90, tags: { run_id: "r", port_no: 1 } });
    act(() => useLiveStore.getState().applyTopologyDelta({ delta_type: "remove", node: { device_id: "d" } }));
    expect(topology.result.current.nodes).toHaveLength(0);
    topology.unmount(); congestion.unmount();
    useLiveStore.getState().reset();
    vi.useRealTimers();
  });

  it("coalesces a telemetry burst into one recomputation per frame and skips unchanged results", () => {
    useLiveStore.getState().reset();
    const scheduler = manualScheduler();
    let renders = 0;
    const { result, unmount } = renderHook(() => { renders += 1; return useTwinLiveCongestion(scheduler); });
    act(() => scheduler.flush());
    const settledRenders = renders;
    const requestsBefore = scheduler.requests;
    act(() => { for (let i = 0; i < 50; i++) useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: telemetry(`d${i}`) }); });
    expect(scheduler.requests - requestsBefore).toBe(1);
    expect(renders).toBe(settledRenders);
    act(() => scheduler.flush());
    expect(renders).toBe(settledRenders + 1);
    expect(Object.keys(result.current)).toHaveLength(50);
    const snapshot = result.current;
    // A metric outside every detector rule changes the store but not the heuristic: the
    // published map keeps its identity, so scene consumers see no change.
    act(() => { useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: telemetry("d0", "temperature", 30, "C") }); scheduler.flush(); });
    expect(result.current).toBe(snapshot);
    unmount();
    expect(scheduler.pending()).toBe(0);
    useLiveStore.getState().reset();
  });

  it("never recomputes topology geometry for telemetry", () => {
    useLiveStore.getState().reset();
    const base = [{ device_id: "a", hostname: "a", device_type: "switch", status: "active", spatial_ref_id: null }];
    const { result } = renderHook(() => useTwinTopology(base));
    const before = result.current;
    act(() => useLiveStore.getState().applyTelemetryDelta({ delta_type: "metric", metric: telemetry("a") }));
    expect(result.current).toBe(before);
    act(() => useLiveStore.getState().applyTopologyDelta({ delta_type: "update", node: { device_id: "a", hostname: "renamed" } }));
    expect(result.current).not.toBe(before);
    expect(result.current.nodeById.a.hostname).toBe("renamed");
    useLiveStore.getState().reset();
  });

  it("merges base topology and live deltas into node list", () => {
    useLiveStore.setState({
      topologyByDeviceId: {
        "device-2": { device_id: "device-2", hostname: "access-2-live", device_type: "switch", status: "active", spatial_ref_id: "campus-a/rack-2" },
      },
      telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [], sceneObjects: {}, sceneObjectIdsNewestFirst: [], alerts: [],
      topologyStatus: "closed", telemetryStatus: "closed", alertsStatus: "closed", digitalTwinStatus: "closed",
    });
    const baseNodes = [{ device_id: "device-1", hostname: "core-1", device_type: "router", status: "active", spatial_ref_id: null }];
    const { result } = renderHook(() => useTwinTopology(baseNodes));
    expect(result.current.nodes).toHaveLength(2);
    expect(result.current.nodes.find((node) => node.id === "device-1")?.hostname).toBe("core-1");
    expect(result.current.nodes.find((node) => node.id === "device-2")).toMatchObject({ hostname: "access-2-live", persistedSpatialRefId: "campus-a/rack-2" });
    useLiveStore.getState().reset();
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
      topologyByDeviceId: {}, telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [],
      sceneObjects: {
        "simulation-state": { id: "simulation-state", object_type: "simulation_state", status: "queued", spatial_ref_id: "campus-a/building-1/floor-2/rack-3/sim-1" },
        "intent-state": { id: "intent-state", object_type: "intent_state", status: "validated", changed_fields: { spatial_ref_id: "campus-a/building-1/floor-1/rack-9/intent-1" } },
      },
      sceneObjectIdsNewestFirst: ["intent-state", "simulation-state"], alerts: [],
      topologyStatus: "closed", telemetryStatus: "closed", alertsStatus: "closed", digitalTwinStatus: "closed",
    });
    const { result } = renderHook(() => useTwinOverlays());
    expect(result.current).toHaveLength(2);
    expect(result.current[0].id).toBe("simulation-state");
    expect(result.current[1].id).toBe("intent-state");
    expect(result.current[1].spatialRefId).toBe("campus-a/building-1/floor-1/rack-9/intent-1");
    useLiveStore.getState().reset();
  });
});

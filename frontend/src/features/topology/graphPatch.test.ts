import { describe, expect, it } from "vitest";
import { applyNewerOverlays, patchDeviceList, patchGraph, patchNodeDetail } from "./graphPatch";
import type { Device, TopologyGraph } from "@/shared/types/network";

const graph: TopologyGraph = {
  nodes: [
    { device_id: "a", hostname: "a", device_type: "router", status: "up", spatial_ref_id: null },
    { device_id: "b", hostname: "b", device_type: "switch", status: "up", spatial_ref_id: "room-1" },
  ],
  edges: [{ source_id: "a", target_id: "b", edge_type: "link", metadata: {} }],
};

describe("topology cache patching (ADR-028 burst handling)", () => {
  it("merges known node fields for existing nodes without a resync", () => {
    const patch = patchGraph(graph, [
      { delta_type: "update", node: { device_id: "a", status: "down" } },
      { delta_type: "update", node: { device_id: "b", spatial_ref_id: null, hostname: "b-renamed" } },
    ]);
    expect(patch.unresolved).toBe(false);
    expect(patch.structural).toBe(false);
    expect(patch.graph.nodes).toEqual([
      { ...graph.nodes[0], status: "down" },
      { ...graph.nodes[1], spatial_ref_id: null, hostname: "b-renamed" },
    ]);
    expect(patch.graph.edges).toBe(graph.edges);
    expect(graph.nodes[0].status).toBe("up");
  });

  it("returns the same graph when a delta changes nothing", () => {
    expect(patchGraph(graph, [{ delta_type: "update", node: { device_id: "a", status: "up" } }]).graph).toBe(graph);
  });

  it("removes nodes with their edges and flags the membership change", () => {
    const patch = patchGraph(graph, [{ delta_type: "remove", node: { device_id: "b" } }]);
    expect(patch.graph.nodes.map((node) => node.device_id)).toEqual(["a"]);
    expect(patch.graph.edges).toEqual([]);
    expect(patch.structural).toBe(true);
  });

  it("reports adds and unknown nodes as unresolved (edges are not in node deltas)", () => {
    expect(patchGraph(graph, [{ delta_type: "add", node: { device_id: "c", hostname: "c" } }]).unresolved).toBe(true);
    expect(patchGraph(graph, [{ delta_type: "update", node: { device_id: "zzz", status: "down" } }]).unresolved).toBe(true);
    expect(patchGraph(graph, [{ delta_type: "add", node: { device_id: "a", status: "degraded" } }]).graph.nodes[0].status).toBe("degraded");
  });

  it("patches cached inventory pages and node details in place", () => {
    const device: Device = { device_id: "a", network_id: "n", hostname: "a", ip_address: "192.0.2.1", device_type: "router", vendor: null, model: null, location_hint: null, spatial_ref_id: null, status: "up", created_at: "t" };
    const list = { items: [device], total: 1, page: 1, page_size: 20 };
    const patched = patchDeviceList(list, [{ delta_type: "update", node: { device_id: "a", status: "down" } }]);
    expect(patched.items[0]).toEqual({ ...device, status: "down" });
    expect(patchDeviceList(list, [{ delta_type: "update", node: { device_id: "other", status: "down" } }])).toBe(list);
    const detail = { node: graph.nodes[0], neighbours: [] };
    expect(patchNodeDetail(detail, [{ delta_type: "update", node: { device_id: "a", status: "down" } }]).node.status).toBe("down");
  });

  it("re-applies only overlays newer than the crawl start", () => {
    const overlays = {
      topologyVersions: { a: { revision: 3 }, b: { revision: 7 } },
      topologyByDeviceId: { a: { device_id: "a", status: "old" }, b: { device_id: "b", status: "maintenance" } },
      topologyTombstones: {},
    };
    expect(applyNewerOverlays(graph, overlays, 5).nodes.map((node) => node.status)).toEqual(["up", "maintenance"]);
    const removed = applyNewerOverlays(graph, { ...overlays, topologyTombstones: { b: 7 } }, 5);
    expect(removed.nodes.map((node) => node.device_id)).toEqual(["a"]);
    expect(applyNewerOverlays(graph, overlays, 10)).toBe(graph);
  });
});

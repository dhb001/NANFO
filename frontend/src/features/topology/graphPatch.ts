import type { DeviceList, TopologyGraph, TopologyNode, TopologyNodeWithNeighbours } from "@/shared/types/network";
import type { TopologyDeltaData } from "@/shared/types/ws";

// Topology deltas are applied to cached REST reads with setQueryData instead of
// re-crawling the whole graph per frame (ADR-028 burst handling). Anything a
// node delta cannot express (a new node's edges, an unknown node) is reported
// as `unresolved`, and the caller runs a full resync.

type NodeDelta = TopologyDeltaData["node"];
const PATCHABLE = ["hostname", "device_type", "status", "spatial_ref_id"] as const;

function nodeFields(node: NodeDelta): Partial<TopologyNode> {
  const fields: Partial<TopologyNode> = {};
  for (const field of PATCHABLE) {
    if (field in node && (node[field] !== undefined)) (fields as Record<string, unknown>)[field] = node[field];
  }
  return fields;
}

function merge<T extends { device_id: string }>(target: T, node: NodeDelta): T {
  const fields = nodeFields(node);
  return Object.entries(fields).some(([key, value]) => (target as Record<string, unknown>)[key] !== value) ? { ...target, ...fields } : target;
}

export interface GraphPatch {
  graph: TopologyGraph;
  /** A delta could not be applied (unknown node, or an add whose edges are unknown): resync. */
  unresolved: boolean;
  /** Membership changed (remove): inventory totals and neighbour/impact reads are stale. */
  structural: boolean;
}

export function patchGraph(graph: TopologyGraph, deltas: readonly TopologyDeltaData[]): GraphPatch {
  let nodes = graph.nodes;
  let edges = graph.edges;
  let unresolved = false;
  let structural = false;
  let index: Map<string, number> | null = null;
  const positions = () => (index ??= new Map(nodes.map((node, position) => [node.device_id, position])));
  for (const delta of deltas) {
    const id = delta?.node?.device_id;
    if (!id) continue;
    const position = positions().get(id);
    if (delta.delta_type === "remove") {
      if (position === undefined) continue;
      nodes = nodes.filter((node) => node.device_id !== id);
      edges = edges.filter((edge) => edge.source_id !== id && edge.target_id !== id);
      index = null;
      structural = true;
    } else if (position === undefined) {
      // New or unknown node: its edges are not carried by a node delta.
      unresolved = true;
    } else {
      const patched = merge(nodes[position], delta.node);
      if (patched !== nodes[position]) {
        if (nodes === graph.nodes) nodes = [...nodes];
        nodes[position] = patched;
      }
    }
  }
  return { graph: nodes === graph.nodes && edges === graph.edges ? graph : { nodes, edges }, unresolved, structural };
}

/** Status/name updates for devices already on a cached inventory page. */
export function patchDeviceList(list: DeviceList, deltas: readonly TopologyDeltaData[]): DeviceList {
  const updates = new Map<string, NodeDelta>();
  for (const delta of deltas) {
    if (delta?.node?.device_id && delta.delta_type !== "remove") updates.set(delta.node.device_id, { ...updates.get(delta.node.device_id), ...delta.node });
  }
  let changed = false;
  const items = list.items.map((device) => {
    const update = updates.get(device.device_id);
    const patched = update ? merge(device, update) : device;
    changed ||= patched !== device;
    return patched;
  });
  return changed ? { ...list, items } : list;
}

export function patchNodeDetail(detail: TopologyNodeWithNeighbours, deltas: readonly TopologyDeltaData[]): TopologyNodeWithNeighbours {
  let node = detail.node;
  for (const delta of deltas) {
    if (delta?.node?.device_id === node.device_id && delta.delta_type !== "remove") node = merge(node, delta.node);
  }
  return node === detail.node ? detail : { ...detail, node };
}

/**
 * Re-apply live overlays recorded after `sinceRevision` to a freshly crawled
 * graph, so a crawl that raced newer deltas never regresses cached state.
 */
export function applyNewerOverlays(
  graph: TopologyGraph,
  overlays: { topologyVersions: Record<string, { revision: number }>; topologyByDeviceId: Record<string, NodeDelta>; topologyTombstones: Record<string, number> },
  sinceRevision: number,
): TopologyGraph {
  const deltas: TopologyDeltaData[] = [];
  for (const [id, version] of Object.entries(overlays.topologyVersions)) {
    if (version.revision <= sinceRevision) continue;
    if (Object.hasOwn(overlays.topologyTombstones, id)) deltas.push({ delta_type: "remove", node: { device_id: id } });
    else if (overlays.topologyByDeviceId[id]) deltas.push({ delta_type: "update", node: overlays.topologyByDeviceId[id] });
  }
  return deltas.length ? patchGraph(graph, deltas).graph : graph;
}

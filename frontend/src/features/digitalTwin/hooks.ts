import { useMemo } from "react";
import { useLiveStore } from "@/features/realtime/store";
import { TopologyEdge, TopologyNode } from "@/shared/types/network";

export interface TwinNode {
  id: string;
  hostname: string;
  type: string;
  status: string;
  x: number;
  y: number;
  z: number;
  spatialRefId: string | null;
}

export interface TwinLink {
  id: string;
  source: [number, number, number];
  target: [number, number, number];
  edgeType: string;
}

interface CanonicalTwinNode {
  device_id: string;
  hostname?: string;
  device_type?: string;
  status?: string;
  spatial_ref_id?: string | null;
}

function hashPosition(seed: string, axis: number) {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash << 5) - hash + seed.charCodeAt(i) + axis * 17;
    hash |= 0;
  }
  const normalized = Math.sin(hash) * 0.5 + 0.5;
  return normalized * 36 - 18;
}

function mergeCanonicalNodes(baseNodes: TopologyNode[], liveNodes: CanonicalTwinNode[]): CanonicalTwinNode[] {
  const merged = new Map<string, CanonicalTwinNode>();

  for (const node of baseNodes) {
    merged.set(node.device_id, node);
  }

  for (const node of liveNodes) {
    const previous = merged.get(node.device_id);
    merged.set(node.device_id, {
      ...(previous ?? {}),
      ...node,
    });
  }

  return Array.from(merged.values());
}

export function useTwinNodes(baseNodes: TopologyNode[] = []) {
  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);

  return useMemo(() => {
    const mergedNodes = mergeCanonicalNodes(baseNodes, Object.values(topologyByDeviceId));

    return mergedNodes.map((node) => {
      const id = node.device_id;
      return {
        id,
        hostname: node.hostname ?? id.slice(0, 8),
        type: node.device_type ?? "device",
        status: node.status ?? "unknown",
        x: hashPosition(id, 1),
        y: hashPosition(id, 2) * 0.22,
        z: hashPosition(id, 3),
        spatialRefId: node.spatial_ref_id ?? null,
      } satisfies TwinNode;
    });
  }, [baseNodes, topologyByDeviceId]);
}

export function useTwinLinks(nodes: TwinNode[], edges: TopologyEdge[] = []): TwinLink[] {
  return useMemo(() => {
    if (nodes.length === 0 || edges.length === 0) {
      return [];
    }

    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const links: TwinLink[] = [];

    for (const edge of edges) {
      const sourceNode = nodeById.get(edge.source_id);
      const targetNode = nodeById.get(edge.target_id);
      if (!sourceNode || !targetNode) {
        continue;
      }
      links.push({
        id: `${edge.source_id}:${edge.target_id}:${edge.edge_type}`,
        source: [sourceNode.x, sourceNode.y, sourceNode.z],
        target: [targetNode.x, targetNode.y, targetNode.z],
        edgeType: edge.edge_type,
      });
    }

    return links;
  }, [edges, nodes]);
}

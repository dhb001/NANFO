import { apiRequest } from "@/shared/lib/api";
import {
  TopologyEdge,
  TopologyDeviceNeighbours,
  TopologyGraph,
  TopologyImpact,
  TopologyNode,
  TopologyNodeWithNeighbours,
  TopologyReconcileResult,
} from "@/shared/types/network";

export const DEFAULT_TOPOLOGY_GRAPH_LIMIT = 200;
export const DEFAULT_MAX_TOPOLOGY_GRAPH_PAGES = 64;

interface TopologyGraphPage {
  data: TopologyGraph;
  nextCursor: string | null;
}

interface TopologyGraphAllOptions {
  pageLimit?: number;
  maxPages?: number;
}

export function getTopologyGraph(
  token: string,
  networkId: string,
  limit = DEFAULT_TOPOLOGY_GRAPH_LIMIT,
  cursor?: string,
): Promise<{ data: TopologyGraph; nextCursor: string | null }> {
  const params = new URLSearchParams({ network_id: networkId, limit: String(limit) });
  if (cursor) {
    params.set("cursor", cursor);
  }

  return apiRequest<TopologyGraph>(`/api/v1/topology/graph?${params.toString()}`, { token }).then((response) => ({
    data: response.data,
    nextCursor: response.meta.next_cursor ?? null,
  }));
}

function mergeTopologyNodes(pages: readonly TopologyGraphPage[]): TopologyNode[] {
  const nodesById = new Map<string, TopologyNode>();

  for (const page of pages) {
    for (const node of page.data.nodes) {
      const existing = nodesById.get(node.device_id);
      if (!existing) {
        nodesById.set(node.device_id, node);
        continue;
      }

      nodesById.set(node.device_id, {
        ...existing,
        ...node,
      });
    }
  }

  return [...nodesById.values()].sort((left, right) => left.device_id.localeCompare(right.device_id));
}

function mergeTopologyEdges(pages: readonly TopologyGraphPage[]): TopologyEdge[] {
  const edgesByKey = new Map<string, TopologyEdge>();

  for (const page of pages) {
    for (const edge of page.data.edges) {
      const key = `${edge.source_id}:${edge.target_id}:${edge.edge_type}`;
      const existing = edgesByKey.get(key);

      if (!existing) {
        edgesByKey.set(key, edge);
        continue;
      }

      edgesByKey.set(key, {
        ...existing,
        ...edge,
        metadata: {
          ...(existing.metadata ?? {}),
          ...(edge.metadata ?? {}),
        },
      });
    }
  }

  return [...edgesByKey.values()].sort((left, right) => {
    const leftKey = `${left.source_id}:${left.target_id}:${left.edge_type}`;
    const rightKey = `${right.source_id}:${right.target_id}:${right.edge_type}`;
    return leftKey.localeCompare(rightKey);
  });
}

function mergeTopologyGraphPages(pages: readonly TopologyGraphPage[]): TopologyGraph {
  return {
    nodes: mergeTopologyNodes(pages),
    edges: mergeTopologyEdges(pages),
  };
}

export async function getTopologyGraphAll(
  token: string,
  networkId: string,
  options: TopologyGraphAllOptions = {},
): Promise<{ data: TopologyGraph; nextCursor: string | null }> {
  const pageLimit = options.pageLimit ?? DEFAULT_TOPOLOGY_GRAPH_LIMIT;
  const maxPages = Math.max(1, options.maxPages ?? DEFAULT_MAX_TOPOLOGY_GRAPH_PAGES);

  const pages: TopologyGraphPage[] = [];
  let cursor: string | undefined;
  let nextCursor: string | null = null;

  for (let page = 0; page < maxPages; page += 1) {
    const response = await getTopologyGraph(token, networkId, pageLimit, cursor);
    pages.push(response);
    nextCursor = response.nextCursor;
    if (!nextCursor) {
      break;
    }
    cursor = nextCursor;
  }

  return {
    data: mergeTopologyGraphPages(pages),
    nextCursor,
  };
}

export function getTopologyNode(token: string, deviceId: string, depth = 1) {
  return apiRequest<TopologyNodeWithNeighbours>(`/api/v1/topology/nodes/${deviceId}?depth=${depth}`, {
    token,
  });
}

export function getTopologyDeviceNeighbours(token: string, deviceId: string, depth = 1, limit = 200) {
  const params = new URLSearchParams({ depth: String(depth), limit: String(limit) });
  return apiRequest<TopologyDeviceNeighbours>(`/api/v1/topology/device/${deviceId}/neighbors?${params.toString()}`, {
    token,
  });
}

export function getTopologyImpact(token: string, deviceId: string, maxHops = 3, limit = 500) {
  const params = new URLSearchParams({ max_hops: String(maxHops), limit: String(limit) });
  return apiRequest<TopologyImpact>(`/api/v1/topology/impact/${deviceId}?${params.toString()}`, {
    token,
  });
}

export function reconcileTopology(token: string, networkId: string) {
  return apiRequest<TopologyReconcileResult>("/api/v1/topology/reconcile", {
    method: "POST",
    body: { network_id: networkId },
    token,
  });
}

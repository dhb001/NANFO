import { apiRequest } from "@/shared/lib/api";
import {
  TopologyDeviceNeighbours,
  TopologyGraph,
  TopologyImpact,
  TopologyNodeWithNeighbours,
  TopologyReconcileResult,
} from "@/shared/types/network";

export function getTopologyGraph(
  token: string,
  networkId: string,
  limit = 200,
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

import { apiRequest } from "@/shared/lib/api";
import { TopologyGraph, TopologyNodeWithNeighbours } from "@/shared/types/network";

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

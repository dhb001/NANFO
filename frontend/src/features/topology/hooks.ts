import { useQuery } from "@tanstack/react-query";
import { getTopologyGraph, getTopologyNode } from "@/features/topology/api";

export function useTopologyGraph(token: string | null, networkId: string | null) {
  return useQuery({
    queryKey: ["topology", token, networkId],
    queryFn: () => getTopologyGraph(token as string, networkId as string),
    enabled: Boolean(token && networkId),
  });
}

export function useTopologyNode(token: string | null, deviceId: string | null) {
  return useQuery({
    queryKey: ["topology-node", token, deviceId],
    queryFn: async () => {
      const response = await getTopologyNode(token as string, deviceId as string, 1);
      return response.data;
    },
    enabled: Boolean(token && deviceId),
  });
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useLiveStore } from "@/features/realtime/store";
import {
  getTopologyDeviceNeighbours,
  getTopologyGraphAll,
  getTopologyImpact,
  getTopologyNode,
  reconcileTopology,
} from "@/features/topology/api";

export function useTopologyGraph(token: string | null, networkId: string | null) {
  const query = useQuery({
    queryKey: ["topology", token, networkId],
    queryFn: async () => {
      const { epoch, topologyRevision: revision } = useLiveStore.getState();
      const result = await getTopologyGraphAll(token as string, networkId as string);
      return { ...result, snapshot: { epoch, revision } };
    },
    enabled: Boolean(token && networkId),
  });
  useEffect(() => {
    const result = query.data;
    if (result && !result.nextCursor) {
      useLiveStore.getState().reconcileTopologySnapshot(result.data.nodes.map((node) => node.device_id), result.snapshot.epoch, result.snapshot.revision);
    }
  }, [query.data]);
  return query;
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

export function useTopologyNeighbours(token: string | null, deviceId: string | null, depth = 1, limit = 200) {
  return useQuery({
    queryKey: ["topology-neighbours", token, deviceId, depth, limit],
    queryFn: () => getTopologyDeviceNeighbours(token as string, deviceId as string, depth, limit).then((response) => response.data),
    enabled: Boolean(token && deviceId),
  });
}

export function useTopologyImpact(token: string | null, deviceId: string | null, maxHops = 3, limit = 500) {
  return useQuery({
    queryKey: ["topology-impact", token, deviceId, maxHops, limit],
    queryFn: () => getTopologyImpact(token as string, deviceId as string, maxHops, limit).then((response) => response.data),
    enabled: Boolean(token && deviceId),
  });
}

export function useReconcileTopology(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => reconcileTopology(token as string, networkId as string).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["topology", token, networkId] });
    },
  });
}

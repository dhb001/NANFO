import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useLiveStore } from "@/features/realtime/store";
import { useSessionScope } from "@/features/auth/sessionScope";
import { scopedKey } from "@/shared/lib/queryKeys";
import { useAuthStore } from "@/shared/state/auth-store";
import { applyNewerOverlays } from "@/features/topology/graphPatch";
import {
  getTopologyDeviceNeighbours,
  getTopologyGraphAll,
  getTopologyImpact,
  getTopologyNode,
  reconcileTopology,
} from "@/features/topology/api";

// Keys are `[domain, sessionKey, authority, ...]` (ADR-028): token rotation keeps
// the graph cache, so the Twin canvas and analysis views never remount on it.

export function useTopologyGraph(token: string | null, networkId: string | null) {
  const scope = useSessionScope();
  const query = useQuery({
    queryKey: scopedKey(scope, "topology", networkId),
    queryFn: async ({ signal }) => {
      const { epoch, topologyRevision: revision } = useLiveStore.getState();
      const result = await scope.read((credential) => getTopologyGraphAll(credential, networkId as string, { signal }), signal);
      // Deltas that arrived during the crawl stay applied: a slow crawl never regresses the cache.
      const live = useLiveStore.getState();
      const data = live.epoch === epoch ? applyNewerOverlays(result.data, live, revision) : result.data;
      return { ...result, data, snapshot: { epoch, revision } };
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
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "topology-node", deviceId),
    queryFn: async ({ signal }) => (await scope.read((credential) => getTopologyNode(credential, deviceId as string, 1, signal), signal)).data,
    enabled: Boolean(token && deviceId),
  });
}

export function useTopologyNeighbours(token: string | null, deviceId: string | null, depth = 1, limit = 200) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "topology-neighbours", deviceId, depth, limit),
    queryFn: async ({ signal }) => (await scope.read((credential) => getTopologyDeviceNeighbours(credential, deviceId as string, depth, limit, signal), signal)).data,
    enabled: Boolean(token && deviceId),
  });
}

export function useTopologyImpact(token: string | null, deviceId: string | null, maxHops = 3, limit = 500) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "topology-impact", deviceId, maxHops, limit),
    queryFn: async ({ signal }) => (await scope.read((credential) => getTopologyImpact(credential, deviceId as string, maxHops, limit, signal), signal)).data,
    enabled: Boolean(token && deviceId),
  });
}

export function useReconcileTopology(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: () => reconcileTopology(useAuthStore.getState().accessToken ?? (token as string), networkId as string).then((response) => response.data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "topology", networkId) });
    },
  });
}

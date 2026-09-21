import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { hasPermission } from "@/features/auth/permissions";
import type { PutSpatialScene } from "@/shared/types/spatial";
import { getSpatialScene, putSpatialScene } from "./spatialApi";

export function useSpatialScene(token: string | null, networkId: string | null, canRead: boolean) {
  return useQuery({
    queryKey: ["spatial-scene", token, networkId],
    queryFn: ({ signal }) => getSpatialScene(token!, networkId!, signal),
    enabled: Boolean(token && networkId && canRead),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useSaveSpatialScene(token: string | null, networkId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: PutSpatialScene) => {
      const auth = useAuthStore.getState();
      if (!token || !networkId || auth.endingSession || !hasPermission(auth.profile, "write:config") || useWorkspaceStore.getState().networkId !== networkId) throw new Error("Current network and write:config permission required.");
      return putSpatialScene(token, networkId, body);
    },
    retry: false,
    onSuccess: (data) => client.setQueryData(["spatial-scene", token, networkId], data),
  });
}

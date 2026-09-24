import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { hasPermission } from "@/features/auth/permissions";
import { useSessionScope } from "@/features/auth/sessionScope";
import { scopedKey } from "@/shared/lib/queryKeys";
import type { PutSpatialScene } from "@/shared/types/spatial";
import { getSpatialScene, putSpatialScene } from "./spatialApi";

/** `token` only gates the query; the key is session-scoped and the credential is read at call time. */
export function useSpatialScene(token: string | null, networkId: string | null, canRead: boolean) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "spatial-scene", networkId),
    queryFn: ({ signal }) => scope.read((credential) => getSpatialScene(credential, networkId!, signal), signal),
    enabled: Boolean(token && networkId && canRead),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useSaveSpatialScene(token: string | null, networkId: string | null) {
  const client = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (body: PutSpatialScene) => {
      const auth = useAuthStore.getState();
      if (!token || !networkId || auth.endingSession || !hasPermission(auth.profile, "write:config") || useWorkspaceStore.getState().networkId !== networkId) throw new Error("Current network and write:config permission required.");
      return scope.request((credential) => putSpatialScene(credential, networkId, body));
    },
    retry: false,
    onSuccess: (data) => client.setQueryData(scopedKey(scope, "spatial-scene", networkId), data),
  });
}

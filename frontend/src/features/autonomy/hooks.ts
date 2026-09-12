import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAutonomy, stopAutonomy, updateAutonomy } from "./api";
import type { AutonomyStatus, AutonomyUpdate } from "./types";
import { ApiClientError } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { hasPermission } from "@/features/auth/permissions";

export const AUTONOMY_POLL_MS = 10_000;
export const AUTONOMY_FRESH_MS = 30_000;

export function useAutonomy() {
  const token = useAuthStore((state) => state.accessToken);
  const profile = useAuthStore((state) => state.profile);
  const generation = useAuthStore((state) => state.generation);
  const endingSession = useAuthStore((state) => state.endingSession);
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const client = useQueryClient();
  const canRead = hasPermission(profile, "read:telemetry");
  const canWrite = canRead && hasPermission(profile, "write:config") && hasPermission(profile, "execute:rollback");
  const enabled = Boolean(token && organizationId && workspaceId && networkId && canRead && !endingSession);
  const queryKey = ["autonomy", generation, token, organizationId, workspaceId, networkId, profile?.permissions];
  const status = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const result = await getAutonomy(token!, networkId!, workspaceId!, signal);
      const confirmed = client.getQueryData<AutonomyStatus>(queryKey);
      if (confirmed && result.revision < confirmed.revision) {
        throw new ApiClientError("Older control revision received. Refresh status before changing mode.", "AUTONOMY_STALE_REVISION");
      }
      return result;
    },
    enabled,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: false,
    refetchInterval: (query) => {
      const error = query.state.error;
      if (error instanceof ApiClientError && (error.status === 401 || error.status === 403)) return false;
      return Math.min(AUTONOMY_POLL_MS * 2 ** Math.min(query.state.fetchFailureCount, 2), 30_000);
    },
  });
  function assertCurrent() {
    const auth = useAuthStore.getState();
    const scope = useWorkspaceStore.getState();
    if (!enabled || !canWrite || auth.endingSession || auth.generation !== generation ||
        auth.accessToken !== token || scope.organizationId !== organizationId ||
        scope.workspaceId !== workspaceId || scope.networkId !== networkId ||
        !["read:telemetry", "write:config", "execute:rollback"].every((permission) => hasPermission(auth.profile, permission))) {
      throw new Error("Current session, scope and write permissions are required.");
    }
  }
  const reconcile = () => {
    // Never repopulate a departed scope from a late mutation callback.
    try { assertCurrent(); } catch { return; }
    void client.invalidateQueries({ queryKey, exact: true });
  };
  const confirm = async (result: AutonomyStatus) => {
    try { assertCurrent(); } catch { return; }
    await client.cancelQueries({ queryKey, exact: true });
    try { assertCurrent(); } catch { return; }
    client.setQueryData<AutonomyStatus>(queryKey, (current) =>
      current && current.revision > result.revision ? current : result);
  };
  const update = useMutation({
    mutationFn: (input: AutonomyUpdate) => {
      assertCurrent();
      if (input.network_id !== networkId) throw new Error("Selected network changed.");
      return updateAutonomy(token!, workspaceId!, input);
    },
    retry: false,
    onSuccess: confirm,
    onSettled: reconcile,
  });
  const stop = useMutation({
    mutationFn: () => {
      assertCurrent();
      return stopAutonomy(token!, networkId!, workspaceId!);
    },
    retry: false,
    onSuccess: confirm,
    onSettled: reconcile,
  });
  return { status, update, stop, enabled, canRead, canWrite, networkId, workspaceId, organizationId };
}

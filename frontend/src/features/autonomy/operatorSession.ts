import { useQueryClient } from "@tanstack/react-query";
import { hasPermission } from "@/features/auth/permissions";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useSessionScope } from "@/features/auth/sessionScope";

// Every request is bound to the captured session; late writes never refill another scope.
export function useOperatorSession() {
  const auth = useAuthStore();
  const scope = useWorkspaceStore();
  const client = useQueryClient();
  const session = useSessionScope();
  const { accessToken: token, generation, profile, endingSession } = auth;
  const { organizationId, workspaceId, networkId } = scope;
  const canRead = hasPermission(profile, "read:telemetry");
  const canWrite = canRead && hasPermission(profile, "write:config") && hasPermission(profile, "execute:rollback");
  const enabled = Boolean(token && organizationId && workspaceId && networkId && canRead && !endingSession);
  const identity = [generation, organizationId, workspaceId, networkId, session.authority];
  function assertCurrent(write = false) {
    const currentAuth = useAuthStore.getState();
    const currentScope = useWorkspaceStore.getState();
    session.assertCurrent();
    if (!enabled || currentAuth.endingSession || currentAuth.generation !== generation || !currentAuth.accessToken ||
        currentScope.organizationId !== organizationId || currentScope.workspaceId !== workspaceId || currentScope.networkId !== networkId ||
        !(write ? ["read:telemetry", "write:config", "execute:rollback"] : ["read:telemetry"]).every((permission) => hasPermission(currentAuth.profile, permission))) {
      throw new Error("Current session, network scope and permissions are required.");
    }
  }
  function reconcile() {
    try { assertCurrent(); } catch { return; }
    void client.invalidateQueries({ queryKey: ["autonomy", ...identity] });
    void client.invalidateQueries({ queryKey: ["autonomy-operator", ...identity] });
  }
  return { get token() { return session.token(); }, networkId, workspaceId, canRead, canWrite, enabled, identity, assertCurrent, reconcile };
}

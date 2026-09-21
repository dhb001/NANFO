import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { ApiClientError } from "@/shared/lib/errors";

function scopeKey(auth = useAuthStore.getState(), scope = useWorkspaceStore.getState()) {
  return JSON.stringify([auth.generation, auth.userId, scope.organizationId, scope.workspaceId, scope.networkId]);
}

export function authorityKey(profile = useAuthStore.getState().profile) {
  return JSON.stringify([[...(profile?.permissions ?? [])].sort(), [...(profile?.roles ?? [])].sort()]);
}

// Capture identity, not credentials: an old async callback may use a rotated
// credential only while it still belongs to this same session and tenant.
export function useSessionScope() {
  const auth = useAuthStore();
  const scope = useWorkspaceStore();
  const key = scopeKey(auth, scope);
  const authority = authorityKey(auth.profile);
  function assertCurrent() {
    if (key !== scopeKey() || useAuthStore.getState().endingSession) {
      throw new ApiClientError("Session context changed", "API_STALE_CONTEXT");
    }
  }
  function token() {
    assertCurrent();
    const value = useAuthStore.getState().accessToken;
    if (!value) throw new ApiClientError("Authentication required", "API_NO_SESSION");
    return value;
  }
  async function request<T>(operation: (credential: string) => Promise<T>): Promise<T> {
    const result = await operation(token());
    assertCurrent();
    return result;
  }
  async function read<T>(operation: (credential: string) => Promise<T>, signal?: AbortSignal): Promise<T> {
    const result = await request(operation);
    if (signal?.aborted || authority !== authorityKey()) {
      throw new ApiClientError("Read authority changed", "API_STALE_CONTEXT");
    }
    return result;
  }
  const urlScope = JSON.stringify([auth.userId, scope.organizationId, scope.workspaceId, scope.networkId]);
  return { key, urlScope, authority, token, request, read, assertCurrent };
}

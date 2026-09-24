import { useShallow } from "zustand/react/shallow";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { ApiClientError } from "@/shared/lib/errors";
import type { UserProfile } from "@/shared/types/auth";

interface ScopeIdentity {
  generation: number;
  userId: string | null;
  organizationId: string | null;
  workspaceId: string | null;
  networkId: string | null;
}

function currentIdentity(): ScopeIdentity {
  const auth = useAuthStore.getState();
  const scope = useWorkspaceStore.getState();
  return { generation: auth.generation, userId: auth.userId, organizationId: scope.organizationId,
    workspaceId: scope.workspaceId, networkId: scope.networkId };
}

function scopeKey(identity: ScopeIdentity = currentIdentity()) {
  return JSON.stringify([identity.generation, identity.userId, identity.organizationId, identity.workspaceId, identity.networkId]);
}

export function authorityKey(profile: UserProfile | null = useAuthStore.getState().profile) {
  return JSON.stringify([[...(profile?.permissions ?? [])].sort(), [...(profile?.roles ?? [])].sort()]);
}

/**
 * Capture identity, not credentials: an old async callback may use a rotated
 * credential only while it still belongs to this same session and tenant.
 *
 * `key` + `authority` are the React Query identity for every server read
 * (ADR-028): access-token rotation never changes them, so caches, mounted
 * views and the Twin canvas survive the 15-minute rotation. Query functions
 * read the current credential at call time via `read`/`request`.
 */
export function useSessionScope() {
  // Selective subscriptions: a token rotation does not re-render consumers.
  const auth = useAuthStore(useShallow((state) => ({ generation: state.generation, userId: state.userId, profile: state.profile })));
  const scope = useWorkspaceStore(useShallow((state) => ({
    organizationId: state.organizationId, workspaceId: state.workspaceId, networkId: state.networkId,
  })));
  const key = scopeKey({ ...auth, ...scope });
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

export type SessionScope = ReturnType<typeof useSessionScope>;

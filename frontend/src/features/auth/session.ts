import { getProfile, logout, refresh } from "@/features/auth/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { queryClient } from "@/app/queryClient";
import { ApiClientError } from "@/shared/lib/errors";
import type { SocketUpgradeRecovery } from "@/shared/types/ws";

function clearContext() {
  void queryClient.cancelQueries();
  queryClient.clear();
  useLiveStore.getState().reset();
}

// Synchronous subscriptions invalidate old context before another socket event can run.
useAuthStore.subscribe((state, previous) => {
  if (state.generation !== previous.generation || state.userId !== previous.userId) {
    clearContext();
    useWorkspaceStore.getState().reset();
    useExecutionModeStore.getState().reset();
    useUiStore.setState({ commandPaletteOpen: false, toasts: [] });
  } else if (JSON.stringify(state.profile?.permissions) !== JSON.stringify(previous.profile?.permissions) ||
      JSON.stringify(state.profile?.roles) !== JSON.stringify(previous.profile?.roles)) {
    clearContext();
  }
});
useWorkspaceStore.subscribe((state, previous) => {
  if (state.organizationId !== previous.organizationId || state.workspaceId !== previous.workspaceId ||
      state.networkId !== previous.networkId) clearContext();
});

let refreshFlight: { generation: number; promise: Promise<boolean> } | null = null;

export function refreshSession(forLogout = false): Promise<boolean> {
  const session = useAuthStore.getState();
  if (session.endingSession && !forLogout) return Promise.resolve(false);
  if (refreshFlight?.generation === session.generation) return refreshFlight.promise;
  if (!session.refreshToken || !session.userId) {
    session.clearSession();
    return Promise.resolve(false);
  }
  const refreshToken = session.refreshToken;
  const isCurrent = () => useAuthStore.getState().generation === session.generation;
  const promise = (async () => {
    try {
      const pair = await refresh(refreshToken);
      if (!isCurrent()) return false;
      if (!pair.access_token || !pair.refresh_token) throw new Error("Incomplete token pair");
      session.replaceTokens({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
      if (useAuthStore.getState().endingSession) return true;
      const profile = await getProfile(pair.access_token);
      if (!isCurrent()) return false;
      if (profile.user_id !== session.userId) throw new Error("Session identity changed");
      session.setProfile(profile);
      return true;
    } catch {
      if (isCurrent() && !useAuthStore.getState().endingSession) session.clearSession();
      return false;
    } finally {
      if (refreshFlight?.generation === session.generation) refreshFlight = null;
    }
  })();
  refreshFlight = { generation: session.generation, promise };
  return promise;
}

export async function logoutSession() {
  const session = useAuthStore.getState();
  if (session.endingSession) return;
  useAuthStore.setState({ endingSession: true });
  try {
    // A rotation already in flight must settle so logout revokes the current pair.
    if (refreshFlight?.generation === session.generation && !await refreshFlight.promise) {
      throw new Error("Backend revocation could not be confirmed: session refresh failed.");
    }
    const current = useAuthStore.getState();
    if (current.generation !== session.generation || !current.accessToken) return;
    try {
      const result = await logout(current.accessToken);
      if (!result.logged_out) throw new Error("Backend revocation could not be confirmed.");
    } catch (error) {
      if (!(error instanceof ApiClientError) || error.status !== 401) throw error;
      if (useAuthStore.getState().generation !== session.generation) return;
      if (!await refreshSession(true)) throw new Error("Backend revocation could not be confirmed: session refresh failed.");
      const rotated = useAuthStore.getState();
      if (rotated.generation !== session.generation || !rotated.accessToken) return;
      const result = await logout(rotated.accessToken);
      if (!result.logged_out) throw new Error("Backend revocation could not be confirmed.");
    }
  } finally {
    if (useAuthStore.getState().generation === session.generation) session.clearSession();
  }
}

let upgradeProbe: { token: string; generation: number; promise: Promise<SocketUpgradeRecovery> } | null = null;

export function recoverSocketUpgrade(token: string): Promise<SocketUpgradeRecovery> {
  const session = useAuthStore.getState();
  if (session.endingSession || session.accessToken !== token) return Promise.resolve("conclusive");
  if (upgradeProbe?.token === token && upgradeProbe.generation === session.generation) return upgradeProbe.promise;
  const isCurrent = () => useAuthStore.getState().generation === session.generation &&
    useAuthStore.getState().accessToken === token && !useAuthStore.getState().endingSession;
  const promise = (async (): Promise<SocketUpgradeRecovery> => {
    try {
      const profile = await getProfile(token);
      if (!isCurrent()) return "conclusive";
      if (profile.user_id !== session.userId) session.clearSession();
      else session.setProfile(profile);
      return "conclusive";
    } catch (error) {
      // Browser 1006 also means transport outage. Only a confirmed REST 401 rotates tokens.
      if (!isCurrent()) return "conclusive";
      if (error instanceof ApiClientError && error.status === 401) {
        await refreshSession();
        return "conclusive";
      }
      if (error instanceof ApiClientError && error.status === 403) return "conclusive";
      return "inconclusive";
    } finally {
      if (upgradeProbe?.token === token && upgradeProbe.generation === session.generation) upgradeProbe = null;
    }
  })();
  upgradeProbe = { token, generation: session.generation, promise };
  return promise;
}

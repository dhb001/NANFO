import { getProfile, logout, refresh } from "@/features/auth/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { tabIdentity } from "@/shared/state/tab-identity";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { queryClient } from "@/app/queryClient";
import { ApiClientError } from "@/shared/lib/errors";
import { nextBackoffMs } from "@/shared/lib/backoff";
import type { SessionRecovery } from "@/shared/state/auth-store";
import type { TokenPair, UserProfile } from "@/shared/types/auth";
import type { SocketUpgradeRecovery } from "@/shared/types/ws";

function clearContext() {
  void queryClient.cancelQueries();
  queryClient.clear();
  useLiveStore.getState().reset();
}

// Synchronous subscriptions invalidate old context before another socket event can run.
useAuthStore.subscribe((state, previous) => {
  if (state.generation !== previous.generation || state.userId !== previous.userId) {
    if (recoveryTimer && recoveryTimer.generation !== state.generation) cancelRecoveryTimer();
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

/** Only these answers prove the credential family is gone; everything else is transient (ADR-028). */
const AUTHORITATIVE_STATUSES = new Set([400, 401, 403]);
export function isAuthoritativeAuthFailure(error: unknown): boolean {
  return error instanceof ApiClientError && AUTHORITATIVE_STATUSES.has(error.status ?? 0);
}

export const SESSION_RECOVERY_BACKOFF = { baseMs: 2_000, capMs: 60_000 } as const;
const MIN_RECOVERY_DELAY_MS = 1_000;

let refreshFlight: { generation: number; promise: Promise<boolean> } | null = null;
let recoveryTimer: { generation: number; handle: number } | null = null;

function cancelRecoveryTimer() {
  if (recoveryTimer) window.clearTimeout(recoveryTimer.handle);
  recoveryTimer = null;
}

function scheduleRecovery(generation: number, reason: SessionRecovery["reason"], error: unknown) {
  const state = useAuthStore.getState();
  if (state.generation !== generation || state.endingSession) return;
  const attempt = (state.recovery?.attempt ?? 0) + 1;
  const requested = error instanceof ApiClientError ? error.retryAfterMs : null;
  const delay = Math.max(MIN_RECOVERY_DELAY_MS, requested ?? nextBackoffMs(attempt, SESSION_RECOVERY_BACKOFF));
  cancelRecoveryTimer();
  recoveryTimer = {
    generation,
    handle: window.setTimeout(() => {
      recoveryTimer = null;
      const current = useAuthStore.getState();
      if (current.generation === generation && !current.endingSession) void refreshSession();
    }, delay),
  };
  state.setRecovery({ retryAt: Date.now() + delay, attempt, reason });
}

function recovered() {
  const wasRecovering = useAuthStore.getState().recovery !== null;
  cancelRecoveryTimer();
  if (!wasRecovering) return;
  useAuthStore.getState().setRecovery(null);
  // Views that failed while the session was reconnecting reload once it is back.
  void queryClient.refetchQueries({ type: "active", predicate: (query) => query.state.status === "error" });
}

/**
 * Single-flight token rotation for this tab.
 *
 * Resolves true only when a fresh pair AND a re-verified profile for the same
 * user are in place. Authoritative 400/401/403 answers end the session; network
 * errors, timeouts, 429 and 5xx keep it, mark it "reconnecting" and retry after
 * `Retry-After` (or a jittered backoff). Callers during that wait get `false`
 * without another request.
 */
export function refreshSession(forLogout = false): Promise<boolean> {
  const session = useAuthStore.getState();
  if (session.endingSession && !forLogout) return Promise.resolve(false);
  if (refreshFlight?.generation === session.generation) return refreshFlight.promise;
  if (!session.refreshToken || !session.userId) {
    session.clearSession();
    return Promise.resolve(false);
  }
  if (!forLogout && recoveryTimer?.generation === session.generation) return Promise.resolve(false);
  const refreshToken = session.refreshToken;
  const generation = session.generation;
  const isCurrent = () => useAuthStore.getState().generation === generation;
  const promise = (async () => {
    try {
      // A copied tab must never rotate the family it inherited.
      if (tabIdentity.state() === null) await tabIdentity.ownership;
      if (!isCurrent()) return false;
      let pair: TokenPair;
      try {
        pair = await refresh(refreshToken);
      } catch (error) {
        if (!isCurrent()) return false;
        if (isAuthoritativeAuthFailure(error)) {
          if (!useAuthStore.getState().endingSession) session.clearSession();
        } else if (!forLogout) {
          scheduleRecovery(generation, "refresh_unavailable", error);
        }
        return false;
      }
      if (!isCurrent()) return false;
      if (!pair?.access_token || !pair.refresh_token) {
        // A re-presented token within the backend grace window returns the same pair (C9).
        if (!forLogout) scheduleRecovery(generation, "refresh_unavailable", null);
        return false;
      }
      // Persist first: the previous refresh token is spent once the server rotated it.
      session.replaceTokens({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
      if (useAuthStore.getState().endingSession) return true;
      let profile: UserProfile;
      try {
        profile = await getProfile(pair.access_token);
      } catch (error) {
        if (!isCurrent()) return false;
        if (isAuthoritativeAuthFailure(error)) session.clearSession();
        else scheduleRecovery(generation, "profile_unavailable", error);
        // Authority is unverified: callers must not replay approved writes on it.
        return false;
      }
      if (!isCurrent()) return false;
      if (profile.user_id !== session.userId) {
        session.clearSession();
        return false;
      }
      useAuthStore.getState().setProfile(profile);
      recovered();
      return true;
    } catch (error) {
      // Never reject: an unexpected client failure is not proof the family is gone.
      if (isCurrent() && !forLogout) scheduleRecovery(generation, "refresh_unavailable", error);
      return false;
    } finally {
      if (refreshFlight?.generation === generation) refreshFlight = null;
    }
  })();
  refreshFlight = { generation, promise };
  return promise;
}

/** Operator-initiated retry from the "Reconnecting" banner; skips the remaining wait once. */
export function retrySessionNow(): Promise<boolean> {
  if (recoveryTimer?.generation === useAuthStore.getState().generation) cancelRecoveryTimer();
  return refreshSession();
}

export async function logoutSession() {
  const session = useAuthStore.getState();
  if (session.endingSession) return;
  useAuthStore.setState({ endingSession: true });
  cancelRecoveryTimer();
  try {
    // A rotation already in flight must settle so logout revokes the current pair.
    if (refreshFlight?.generation === session.generation) await refreshFlight.promise;
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

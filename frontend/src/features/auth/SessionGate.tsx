import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { getProfile } from "@/features/auth/api";
import { refreshSession } from "@/features/auth/session";
import { SessionRecoveryBanner } from "@/features/auth/SessionRecoveryBanner";
import { useAuthStore } from "@/shared/state/auth-store";
import { ApiClientError, describeApiError } from "@/shared/lib/errors";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Button } from "@/shared/ui/Button";

export function SessionGate({ children }: { children: JSX.Element }) {
  const token = useAuthStore((state) => state.accessToken);
  const profile = useAuthStore((state) => state.profile);
  const ownership = useAuthStore((state) => state.ownership);
  const recovering = useAuthStore((state) => state.recovery !== null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!token || profile) return;
    let active = true;
    const generation = useAuthStore.getState().generation;
    const isCurrent = () => active && useAuthStore.getState().generation === generation;
    void getProfile(token).then((next) => {
      if (!isCurrent()) return;
      if (next.user_id !== useAuthStore.getState().userId) useAuthStore.getState().clearSession();
      else useAuthStore.getState().setProfile(next);
    }).catch((failure: unknown) => {
      if (!isCurrent()) return;
      // A 401 rotates (single-flight); outages keep the session and show a retry.
      if (failure instanceof ApiClientError && failure.status === 401) void refreshSession();
      else setError(failure);
    });
    return () => { active = false; };
  }, [token, profile, attempt]);
  if (!token) return <Navigate to="/login" replace />;
  // Wait for the duplicate-tab check too: a copied tab must not open the workspace.
  if (!profile || ownership === null) {
    if (recovering) return <div style={{ maxWidth: 680, margin: "15vh auto", padding: "0 1rem" }}><SessionRecoveryBanner /></div>;
    return <AsyncState title={error ? "Profile unavailable" : "Verifying session"}
      description={error ? describeApiError(error) : "Permissions are loaded from the backend before opening the workspace."}
      action={error ? <Button onClick={() => { setError(null); setAttempt(attempt + 1); }}>Retry</Button> : undefined} />;
  }
  return children;
}

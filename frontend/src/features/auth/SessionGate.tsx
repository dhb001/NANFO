import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { getProfile } from "@/features/auth/api";
import { refreshSession } from "@/features/auth/session";
import { useAuthStore } from "@/shared/state/auth-store";
import { ApiClientError } from "@/shared/lib/errors";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Button } from "@/shared/ui/Button";

export function SessionGate({ children }: { children: JSX.Element }) {
  const token = useAuthStore((state) => state.accessToken);
  const profile = useAuthStore((state) => state.profile);
  const [error, setError] = useState(false);
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
      if (failure instanceof ApiClientError && failure.status === 401) void refreshSession();
      else setError(true);
    });
    return () => { active = false; };
  }, [token, profile, attempt]);
  if (!token) return <Navigate to="/login" replace />;
  if (!profile) return <AsyncState title={error ? "Profile unavailable" : "Verifying session"}
    description="Permissions are loaded from the backend before opening the workspace."
    action={error ? <Button onClick={() => { setError(false); setAttempt(attempt + 1); }}>Retry</Button> : undefined} />;
  return children;
}

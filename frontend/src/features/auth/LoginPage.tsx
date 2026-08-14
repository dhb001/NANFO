import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLogin } from "@/features/auth/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { Button } from "@/shared/ui/Button";
import { AsyncState } from "@/shared/ui/AsyncState";
import { toErrorMessage } from "@/shared/lib/errors";
import { getProfile } from "@/features/auth/api";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("change-me");
  const setSession = useAuthStore((state) => state.setSession);

  const loginMutation = useLogin();

  const isSubmitting = loginMutation.isPending;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const tokenPair = await loginMutation.mutateAsync({ email, password });
    setSession({
      accessToken: tokenPair.access_token,
      refreshToken: tokenPair.refresh_token,
      userId: "pending",
    });

    const profile = await getProfile(tokenPair.access_token);
    if (profile) {
      setSession({
        accessToken: tokenPair.access_token,
        refreshToken: tokenPair.refresh_token,
        userId: profile.user_id,
      });
    }
    navigate("/ops/overview");
  }

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "1rem" }}>
      <div
        style={{
          width: "min(460px, 100%)",
          border: "1px solid var(--line-soft)",
          borderRadius: "var(--radius-l)",
          background: "var(--surface-card)",
          boxShadow: "var(--shadow-mid)",
          padding: "1.1rem",
        }}
      >
        <h1 style={{ fontSize: "1.4rem", marginBottom: "0.3rem" }}>NANFO Access</h1>
        <p style={{ color: "var(--ink-3)", marginBottom: "0.9rem" }}>
          Authenticate with your operator account to continue.
        </p>

        <form onSubmit={onSubmit} style={{ display: "grid", gap: "0.75rem" }}>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Email
            </span>
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              required
              autoFocus
              style={{
                border: "1px solid var(--line-soft)",
                borderRadius: "10px",
                padding: "0.5rem 0.56rem",
                background: "white",
              }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Password
            </span>
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              required
              style={{
                border: "1px solid var(--line-soft)",
                borderRadius: "10px",
                padding: "0.5rem 0.56rem",
                background: "white",
              }}
            />
          </label>

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing In..." : "Sign In"}
            </Button>
          </div>
        </form>

        {loginMutation.isError ? (
          <div style={{ marginTop: "0.8rem" }}>
            <AsyncState
              title="Login failed"
              description={toErrorMessage(loginMutation.error)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

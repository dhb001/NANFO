import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLogin } from "@/features/auth/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { Button } from "@/shared/ui/Button";
import { AsyncState } from "@/shared/ui/AsyncState";
import { toErrorMessage } from "@/shared/lib/errors";
import { getProfile } from "@/features/auth/api";
import { useUiStore } from "@/shared/state/ui-store";
import { BrandMark } from "@/shared/ui/BrandMark";
import { NetworkArtwork } from "@/shared/ui/NetworkArtwork";
import "@/features/auth/session";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const pushToast = useUiStore((state) => state.pushToast);

  const loginMutation = useLogin();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    try {
      const tokenPair = await loginMutation.mutateAsync({ email, password });
      try {
        const profile = await getProfile(tokenPair.access_token);
        setSession({
          accessToken: tokenPair.access_token,
          refreshToken: tokenPair.refresh_token,
          userId: profile.user_id,
          profile,
        });
      } catch {
        clearSession();
        pushToast({
          title: "Profile lookup failed",
          description: "Please sign in again.",
          tone: "danger",
        });
        return;
      }
      navigate("/ops/overview");
    } catch {
      // The mutation exposes the login failure in the form.
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-story" aria-label="NANFO network intelligence">
        <BrandMark />
        <div className="login-story-copy"><div className="eyebrow">The network atlas / NANFO</div><h2>Find clarity.<br /><em>In every<br />connection.</em></h2><p>A considered workspace for observing, understanding and orchestrating your network.</p></div>
        <NetworkArtwork />
        <div className="login-story-footer"><span>01 Observe &nbsp; / &nbsp; 02 Understand &nbsp; / &nbsp; 03 Orchestrate</span><span>N /</span></div>
      </section>
      <div className="login-form-side">
      <div className="login-form">
        <div className="login-entry-mark" aria-hidden="true">↗</div>
        <div className="eyebrow">Your next perspective</div>
        <h1>NANFO Access</h1>
        <p className="login-intro">Welcome back. Your network workspace awaits.</p>

        <form onSubmit={onSubmit}>
          <label>
            <span>Email</span>
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              autoComplete="username"
              required
              autoFocus
              placeholder="you@organization.com"
            />
          </label>

          <label>
            <span>Password</span>
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
              required
              placeholder="Enter your password"
            />
          </label>

            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing In..." : "Sign In"}
            </Button>
        </form>

        {loginMutation.isError ? (
          <div style={{ marginTop: "0.8rem" }}>
            <AsyncState
              title="Login failed"
              description={toErrorMessage(loginMutation.error)}
            />
          </div>
        ) : null}
        <p className="login-note">Sessions stay in this tab. Sign in separately in other tabs to access your workspace.</p>
      </div>
      </div>
    </main>
  );
}

import { useEffect, useState } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { retrySessionNow } from "@/features/auth/session";
import { Button } from "@/shared/ui/Button";

function secondsUntil(retryAt: number, now: number) {
  return Math.max(0, Math.ceil((retryAt - now) / 1000));
}

/** Transient refresh failure: the session is kept and retried; say so instead of logging out. */
function useSessionRecoveryText() {
  const recovery = useAuthStore((state) => state.recovery);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!recovery) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [recovery]);
  if (!recovery) return null;
  const wait = secondsUntil(recovery.retryAt, now);
  const subject = recovery.reason === "profile_unavailable" ? "Your permissions could not be re-verified" : "The sign-in service is temporarily unavailable";
  return `${subject}. Your session is kept and NANFO retries automatically${wait ? ` in ${wait} s` : ""}.`;
}

export function SessionRecoveryBanner() {
  const text = useSessionRecoveryText();
  const [pending, setPending] = useState(false);
  if (!text) return null;
  return (
    <div className="realtime-halt" role="status">
      <span><strong>Reconnecting.</strong> {text}</span>
      <Button tone="ghost" disabled={pending} onClick={() => {
        setPending(true);
        void retrySessionNow().finally(() => setPending(false));
      }}>{pending ? "Retrying…" : "Retry now"}</Button>
    </div>
  );
}

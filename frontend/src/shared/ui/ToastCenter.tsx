import { useEffect, useRef, useState } from "react";
import { useUiStore, type ToastItem } from "@/shared/state/ui-store";

/** Non-danger toasts dismiss themselves; errors stay until dismissed. */
export const TOAST_AUTO_DISMISS_MS = 6_000;

// Tone is conveyed in text as well as colour.
const TONE_LABEL: Record<ToastItem["tone"], string> = { danger: "Error", warn: "Warning", ok: "Success", info: "Notice" };

export function ToastCenter() {
  const toasts = useUiStore((state) => state.toasts);
  const dismissToast = useUiStore((state) => state.dismissToast);
  const [retained, setRetained] = useState(toasts);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    setRetained((previous) => [...toasts, ...previous.filter((item) => !toasts.some((toast) => toast.id === item.id))]);
    const timer = window.setTimeout(() => setRetained(toasts), 200);
    return () => window.clearTimeout(timer);
  }, [toasts]);
  // Each toast counts down from when it appeared; hovering or focusing the toasts pauses
  // auto-dismissal and leaving restarts the countdown (WCAG 2.2.1).
  const shownAt = useRef(new Map<string, number>());
  useEffect(() => {
    if (paused) {
      shownAt.current.clear();
      return;
    }
    const now = Date.now();
    for (const id of shownAt.current.keys()) if (!toasts.some((toast) => toast.id === id)) shownAt.current.delete(id);
    const timers = toasts.filter((toast) => toast.tone !== "danger").map((toast) => {
      const start = shownAt.current.get(toast.id) ?? now;
      shownAt.current.set(toast.id, start);
      return window.setTimeout(() => dismissToast(toast.id), Math.max(0, start + TOAST_AUTO_DISMISS_MS - now));
    });
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [toasts, paused, dismissToast]);
  const visible = [...toasts, ...retained.filter((item) => !toasts.some((toast) => toast.id === item.id))];

  return (
    <div className="toast-center" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false); }}>
        {visible.map((toast) => {
          const open = toasts.some((item) => item.id === toast.id);
          return (
            <div
              key={toast.id}
              className={`toast-presence toast--${toast.tone}`}
              role={toast.tone === "danger" ? "alert" : "status"}
              data-open={open}
              aria-hidden={!open || undefined}
            >
              <button className="toast-dismiss" aria-label={`Dismiss ${toast.title}`} disabled={!open} onClick={() => dismissToast(toast.id)}>×</button>
              <div className="async-title"><span className="toast-tone">{TONE_LABEL[toast.tone]}:</span> {toast.title}</div>
              {toast.description ? <div className="stat-caption">{toast.description}</div> : null}
            </div>
          );
        })}
    </div>
  );
}

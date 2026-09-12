import { useEffect, useState } from "react";
import { useUiStore } from "@/shared/state/ui-store";

export function ToastCenter() {
  const toasts = useUiStore((state) => state.toasts);
  const dismissToast = useUiStore((state) => state.dismissToast);
  const [retained, setRetained] = useState(toasts);
  useEffect(() => {
    setRetained((previous) => [...toasts, ...previous.filter((item) => !toasts.some((toast) => toast.id === item.id))]);
    const timer = window.setTimeout(() => setRetained(toasts), 200);
    return () => window.clearTimeout(timer);
  }, [toasts]);
  const visible = [...toasts, ...retained.filter((item) => !toasts.some((toast) => toast.id === item.id))];

  return (
    <div style={{ position: "fixed", right: 16, bottom: 16, display: "grid", gap: "0.6rem", zIndex: 1100 }}>
        {visible.map((toast) => (
          <button
            key={toast.id}
            className="toast-presence"
            data-open={toasts.some((item) => item.id === toast.id)}
            disabled={!toasts.some((item) => item.id === toast.id)}
            aria-hidden={!toasts.some((item) => item.id === toast.id) || undefined}
            onClick={() => dismissToast(toast.id)}
            style={{
              width: "min(320px, calc(100vw - 32px))",
              textAlign: "left",
              border: "1px solid var(--line-soft)",
              background: "var(--surface-card)",
              borderRadius: "12px",
              boxShadow: "var(--shadow-mid)",
              padding: "0.65rem 0.7rem",
              cursor: "pointer",
            }}
          >
            <div style={{ fontWeight: 700 }}>{toast.title}</div>
            {toast.description ? <div style={{ color: "var(--ink-3)", fontSize: "0.82rem" }}>{toast.description}</div> : null}
          </button>
        ))}
    </div>
  );
}

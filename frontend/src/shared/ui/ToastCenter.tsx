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
    <div className="toast-center" aria-live="polite">
        {visible.map((toast) => (
          <div
            key={toast.id}
            className="toast-presence"
            data-open={toasts.some((item) => item.id === toast.id)}
            aria-hidden={!toasts.some((item) => item.id === toast.id) || undefined}
          >
            <button className="toast-dismiss" aria-label={`Dismiss ${toast.title}`} disabled={!toasts.some((item) => item.id === toast.id)} onClick={() => dismissToast(toast.id)}>×</button>
            <div className="async-title">{toast.title}</div>
            {toast.description ? <div className="stat-caption">{toast.description}</div> : null}
          </div>
        ))}
    </div>
  );
}

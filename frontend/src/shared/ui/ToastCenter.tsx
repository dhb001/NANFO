import { AnimatePresence, m } from "framer-motion";
import { useUiStore } from "@/shared/state/ui-store";

export function ToastCenter() {
  const toasts = useUiStore((state) => state.toasts);
  const dismissToast = useUiStore((state) => state.dismissToast);

  return (
    <div style={{ position: "fixed", right: 16, bottom: 16, display: "grid", gap: "0.6rem", zIndex: 1100 }}>
      <AnimatePresence>
        {toasts.map((toast) => (
          <m.button
            key={toast.id}
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.2 }}
            onClick={() => dismissToast(toast.id)}
            style={{
              width: 320,
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
          </m.button>
        ))}
      </AnimatePresence>
    </div>
  );
}

import { ReactNode } from "react";

interface AsyncStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function AsyncState({ title, description, action }: AsyncStateProps) {
  return (
    <div
      className="async-state-enter"
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "var(--radius-m)",
        background: "var(--surface-card)",
        padding: "1rem",
        boxShadow: "var(--shadow-low)",
      }}
      role="status"
      aria-live="polite"
    >
      <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>{title}</div>
      {description ? <div style={{ color: "var(--ink-3)", marginBottom: action ? "0.75rem" : 0 }}>{description}</div> : null}
      {action}
    </div>
  );
}

import { PropsWithChildren, ReactNode } from "react";

interface PanelProps extends PropsWithChildren {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
}

export function Panel({ title, subtitle, action, children }: PanelProps) {
  return (
    <section
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "var(--radius-m)",
        background: "var(--surface-card)",
        boxShadow: "var(--shadow-low)",
        overflow: "hidden",
      }}
    >
      {title ? (
        <header
          style={{
            padding: "0.8rem 0.9rem",
            borderBottom: "1px solid var(--line-soft)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "0.8rem",
          }}
        >
          <div>
            <h3 style={{ fontSize: "0.98rem", fontWeight: 700 }}>{title}</h3>
            {subtitle ? <p style={{ color: "var(--ink-3)", fontSize: "0.84rem" }}>{subtitle}</p> : null}
          </div>
          {action}
        </header>
      ) : null}
      <div style={{ padding: "0.9rem" }}>{children}</div>
    </section>
  );
}

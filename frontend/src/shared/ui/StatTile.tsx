interface StatTileProps {
  label: string;
  value: string;
  caption?: string;
  tone?: "normal" | "ok" | "warn" | "danger";
}

const toneColor: Record<NonNullable<StatTileProps["tone"]>, string> = {
  normal: "var(--ink-1)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  danger: "var(--danger)",
};

export function StatTile({ label, value, caption, tone = "normal" }: StatTileProps) {
  return (
    <div
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "12px",
        padding: "0.7rem 0.8rem",
        background: "linear-gradient(180deg, #ffffff, var(--surface-card))",
      }}
    >
      <div className="mono" style={{ fontSize: "0.74rem", color: "var(--ink-3)", marginBottom: "0.25rem" }}>
        {label}
      </div>
      <div style={{ fontSize: "1.3rem", fontWeight: 700, color: toneColor[tone] }}>{value}</div>
      {caption ? <div style={{ color: "var(--ink-3)", fontSize: "0.8rem" }}>{caption}</div> : null}
    </div>
  );
}

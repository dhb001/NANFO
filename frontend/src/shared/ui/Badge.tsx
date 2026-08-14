interface BadgeProps {
  text: string;
  tone?: "neutral" | "ok" | "warn" | "danger" | "info";
}

const colors: Record<NonNullable<BadgeProps["tone"]>, { bg: string; fg: string; border: string }> = {
  neutral: {
    bg: "color-mix(in srgb, var(--ink-3) 10%, white)",
    fg: "var(--ink-2)",
    border: "var(--line-soft)",
  },
  ok: {
    bg: "color-mix(in srgb, var(--ok) 16%, white)",
    fg: "var(--ok)",
    border: "color-mix(in srgb, var(--ok) 24%, white)",
  },
  warn: {
    bg: "color-mix(in srgb, var(--warn) 16%, white)",
    fg: "var(--warn)",
    border: "color-mix(in srgb, var(--warn) 24%, white)",
  },
  danger: {
    bg: "color-mix(in srgb, var(--danger) 16%, white)",
    fg: "var(--danger)",
    border: "color-mix(in srgb, var(--danger) 24%, white)",
  },
  info: {
    bg: "color-mix(in srgb, var(--info) 14%, white)",
    fg: "var(--info)",
    border: "color-mix(in srgb, var(--info) 24%, white)",
  },
};

export function Badge({ text, tone = "neutral" }: BadgeProps) {
  const color = colors[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: "999px",
        padding: "0.2rem 0.52rem",
        fontSize: "0.74rem",
        fontWeight: 600,
        background: color.bg,
        color: color.fg,
        border: `1px solid ${color.border}`,
      }}
    >
      {text}
    </span>
  );
}

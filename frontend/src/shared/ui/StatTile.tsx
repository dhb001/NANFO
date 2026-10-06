import type { StatusTone } from "@/shared/lib/statusTones";

interface StatTileProps {
  label: string;
  value: string;
  caption?: string | undefined;
  tone?: "normal" | StatusTone | undefined;
}

const toneColor: Record<NonNullable<StatTileProps["tone"]>, string> = {
  normal: "var(--ink-1)",
  neutral: "var(--ink-1)",
  info: "var(--info)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  danger: "var(--danger)",
};

export function StatTile({ label, value, caption, tone = "normal" }: StatTileProps) {
  return (
    <div className="stat-tile">
      <div className="stat-label">
        {label}
      </div>
      <div className="stat-value" style={{ color: toneColor[tone] }}>{value}</div>
      {caption ? <div className="stat-caption">{caption}</div> : null}
    </div>
  );
}

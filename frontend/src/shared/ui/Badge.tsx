interface BadgeProps {
  text: string;
  tone?: "neutral" | "ok" | "warn" | "danger" | "info";
}

export function Badge({ text, tone = "neutral" }: BadgeProps) {
  return <span className={`badge badge--${tone}`}>{text}</span>;
}

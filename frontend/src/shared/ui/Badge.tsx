import type { StatusTone } from "@/shared/lib/statusTones";

interface BadgeProps {
  text: string;
  tone?: StatusTone;
}

export function Badge({ text, tone = "neutral" }: BadgeProps) {
  return <span className={`badge badge--${tone}`}>{text}</span>;
}

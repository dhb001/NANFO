export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatNumber(value: number, digits = 2): string {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatPercent(value: number): string {
  return `${formatNumber(value, 2)}%`;
}

export function severityColor(score: number): "ok" | "warn" | "danger" {
  if (score >= 0.8) {
    return "ok";
  }
  if (score >= 0.6) {
    return "warn";
  }
  return "danger";
}

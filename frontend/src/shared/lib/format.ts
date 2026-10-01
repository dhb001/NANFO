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

/**
 * Text for a loosely typed backend value (tags, provenance, payload fields): primitives as
 * text, absent values as `missing`, structured values as bounded JSON (never "[object Object]").
 */
export function displayValue(value: unknown, missing = "unavailable"): string {
  if (value === null || value === undefined || value === "") return missing;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return String(value);
  try {
    const text = JSON.stringify(value);
    return text === undefined ? missing : text.length > 200 ? `${text.slice(0, 199)}…` : text;
  } catch {
    return missing;
  }
}

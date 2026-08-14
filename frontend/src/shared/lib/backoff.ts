export function nextBackoffMs(attempt: number): number {
  const base = 400;
  const cap = 5_000;
  return Math.min(base * 2 ** Math.max(0, attempt - 1), cap);
}

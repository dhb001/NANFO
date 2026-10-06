import type { TelemetryHealth } from "@/shared/types/telemetry";

/** "≥ N" when the server stopped counting at its cap (`total_capped`, ADR-028 C12). */
export function formatCappedTotal(total: number, capped: boolean | undefined): string {
  return capped ? `≥ ${total}` : String(total);
}

/** Page count label; a capped total only bounds the page count from below. */
export function formatPageCount(total: number, pageSize: number, capped: boolean | undefined): string {
  const pages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  return capped ? `≥ ${pages}` : String(pages);
}

/** With a capped total, a full page may be followed by more rows than the count shows. */
export function hasNextPage(page: number, pageSize: number, total: number, itemCount: number, capped: boolean | undefined): boolean {
  return capped ? itemCount >= pageSize : page * pageSize < total;
}

/** `total_records` is a planner estimate when `total_records_estimated` is set; never present it as exact. */
export function formatRecordTotal(health: Pick<TelemetryHealth, "total_records" | "total_records_estimated">): string {
  return health.total_records_estimated ? `≈ ${health.total_records}` : String(health.total_records);
}

import { TelemetryAggregation } from "@/shared/types/telemetry";

export function validateHistoryFilters(start: string, end: string, metric: string, aggregation: TelemetryAggregation | "", bucketSeconds: number): string | null {
  const startMs = start ? Date.parse(start) : null;
  const endMs = end ? Date.parse(end) : null;
  if ((startMs !== null && !Number.isFinite(startMs)) || (endMs !== null && !Number.isFinite(endMs))) return "Enter valid dates and times.";
  if (startMs !== null && endMs !== null && startMs >= endMs) return "Start must be before the exclusive end time.";
  if (aggregation) {
    if (metric.trim().startsWith("flow_")) return "flow_* aggregation is unavailable: snapshot v1 has no durable flow match identity; use raw history.";
    if (!metric.trim() || startMs === null || endMs === null) return "Aggregation requires a metric, start time and end time.";
    if (endMs - startMs > 7 * 86400 * 1000) return "Aggregation supports at most seven days.";
    if (!Number.isInteger(bucketSeconds) || bucketSeconds < 1 || bucketSeconds > 86400) return "Bucket seconds must be an integer from 1 to 86400.";
  }
  return null;
}

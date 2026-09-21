import { apiRequest } from "@/shared/lib/api";
import { TelemetryAggregationHistory, TelemetryDeviceHistory, TelemetryHealth, TelemetryHistory, TelemetryHistoryQuery, TelemetryTimeRange } from "@/shared/types/telemetry";

export function getTelemetryHistory(token: string, query: TelemetryHistoryQuery, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.networkId) {
    params.set("network_id", query.networkId);
  }
  if (query.workspaceId) {
    params.set("workspace_id", query.workspaceId);
  }
  if (query.metric) {
    params.set("metric", query.metric);
  }
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 50));
  if (query.startTime) params.set("start_time", query.startTime);
  if (query.endTime) params.set("end_time", query.endTime);
  if (query.aggregation) params.set("aggregation", query.aggregation);
  if (query.bucketSeconds !== undefined) params.set("bucket_seconds", String(query.bucketSeconds));
  return apiRequest<TelemetryHistory | TelemetryAggregationHistory>(`/api/v1/telemetry/history?${params.toString()}`, { token, signal });
}

export function getDeviceTelemetry(token: string, deviceId: string, page = 1, pageSize = 50, metric?: string, range: TelemetryTimeRange = {}, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (metric) {
    params.set("metric", metric);
  }
  if (range.startTime) params.set("start_time", range.startTime);
  if (range.endTime) params.set("end_time", range.endTime);
  return apiRequest<TelemetryDeviceHistory>(`/api/v1/telemetry/device/${deviceId}?${params.toString()}`, { token, signal });
}

export function getTelemetryHealth(token: string, signal?: AbortSignal) {
  return apiRequest<TelemetryHealth>("/api/v1/telemetry/health", { token, signal });
}

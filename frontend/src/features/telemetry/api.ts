import { apiRequest } from "@/shared/lib/api";
import { TelemetryDeviceHistory, TelemetryHealth, TelemetryHistory } from "@/shared/types/telemetry";

interface HistoryQuery {
  networkId?: string;
  workspaceId?: string;
  metric?: string;
  page?: number;
  pageSize?: number;
}

export function getTelemetryHistory(token: string, query: HistoryQuery) {
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
  return apiRequest<TelemetryHistory>(`/api/v1/telemetry/history?${params.toString()}`, { token });
}

export function getDeviceTelemetry(token: string, deviceId: string, page = 1, pageSize = 50, metric?: string) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (metric) {
    params.set("metric", metric);
  }
  return apiRequest<TelemetryDeviceHistory>(`/api/v1/telemetry/device/${deviceId}?${params.toString()}`, { token });
}

export function getTelemetryHealth(token: string) {
  return apiRequest<TelemetryHealth>("/api/v1/telemetry/health", { token });
}

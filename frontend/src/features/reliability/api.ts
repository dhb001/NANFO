import { apiRequest } from "@/shared/lib/api";
import { AlertActionResult, AlertListParams, AlertListResult, AlertRecord, AlertHistoryResult } from "@/shared/types/alerts";

function buildListAlertsQuery(params: AlertListParams): string {
  const query = new URLSearchParams();
  for (const key of ["status", "severity", "source", "search"] as const) {
    if (params[key]) query.set(key, params[key]);
  }
  if (params.correlationId) {
    query.set("correlation_id", params.correlationId);
  }
  query.set("limit", String(params.limit ?? 200));
  if (params.workspaceId) query.set("workspace_id", params.workspaceId);
  if (params.networkId) query.set("network_id", params.networkId);
  return query.toString();
}

export function listAlerts(token: string, params: AlertListParams = {}) {
  const query = buildListAlertsQuery(params);
  const path = query ? `/api/v1/alerts?${query}` : "/api/v1/alerts";
  return apiRequest<AlertListResult>(path, { token });
}

export function acknowledgeAlert(token: string, alertId: string) {
  return apiRequest<AlertActionResult>(`/api/v1/alerts/${alertId}/ack`, {
    method: "POST",
    token,
  });
}

export function resolveAlert(token: string, alertId: string) {
  return apiRequest<AlertActionResult>(`/api/v1/alerts/${alertId}/resolve`, {
    method: "POST",
    token,
  });
}

export function getAlert(token: string, alertId: string) {
  return apiRequest<AlertRecord>(`/api/v1/alerts/${encodeURIComponent(alertId)}`, { token });
}

export function getAlertHistory(token: string, alertId: string) {
  return apiRequest<AlertHistoryResult>(`/api/v1/alerts/${encodeURIComponent(alertId)}/history`, { token });
}

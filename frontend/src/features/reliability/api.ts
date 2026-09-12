import { apiRequest } from "@/shared/lib/api";
import { AlertActionResult, AlertListResult, AlertRecord, AlertHistoryResult } from "@/shared/types/alerts";

interface ListAlertsParams {
  status?: "active" | "acknowledged" | "resolved";
  severity?: string;
  source?: string;
  correlationId?: string;
  search?: string;
  limit?: number;
}

function buildListAlertsQuery(params: ListAlertsParams): string {
  const query = new URLSearchParams();
  for (const key of ["status", "severity", "source", "search"] as const) {
    if (params[key]) query.set(key, params[key]);
  }
  if (params.correlationId) {
    query.set("correlation_id", params.correlationId);
  }
  query.set("limit", String(params.limit ?? 200));
  return query.toString();
}

export function listAlerts(token: string, params: ListAlertsParams = {}) {
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

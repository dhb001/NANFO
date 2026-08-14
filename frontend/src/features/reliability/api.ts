import { apiRequest } from "@/shared/lib/api";
import { AlertActionResult, AlertListResult } from "@/shared/types/alerts";

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
  if (params.status) {
    query.set("status", params.status);
  }
  if (params.severity) {
    query.set("severity", params.severity);
  }
  if (params.source) {
    query.set("source", params.source);
  }
  if (params.correlationId) {
    query.set("correlation_id", params.correlationId);
  }
  if (params.search) {
    query.set("search", params.search);
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

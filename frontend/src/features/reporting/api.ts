import { apiRequest } from "@/shared/lib/api";
import { GenerateReportRequest, ReportGenerateResult, ReportRecord, ReportHistoryResult } from "@/shared/types/reporting";

export function generateReport(token: string, body: GenerateReportRequest, idempotencyKey: string) {
  return apiRequest<ReportGenerateResult>("/api/v1/reports/generate", {
    method: "POST",
    body,
    token,
    headers: {
      "Idempotency-Key": idempotencyKey,
    },
  });
}

export function getReport(token: string, reportId: string, workspaceId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  return apiRequest<ReportRecord>(`/api/v1/reports/${encodeURIComponent(reportId)}?${params.toString()}`, {
    token, signal,
  });
}

export function listReports(token: string, workspaceId: string, page: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: "20" });
  return apiRequest<ReportHistoryResult>(`/api/v1/reports?${params}`, { token, signal });
}

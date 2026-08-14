import { apiRequest } from "@/shared/lib/api";
import { GenerateReportRequest, ReportGenerateResult, ReportRecord } from "@/shared/types/reporting";

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

export function getReport(token: string, reportId: string, workspaceId: string) {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  return apiRequest<ReportRecord>(`/api/v1/reports/${reportId}?${params.toString()}`, {
    token,
  });
}

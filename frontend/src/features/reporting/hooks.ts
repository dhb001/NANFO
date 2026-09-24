import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { generateReport, getReport, listReports } from "@/features/reporting/api";
import { isReportTerminal } from "@/features/reporting/logic";
import { useSessionScope } from "@/features/auth/sessionScope";
import { samePageSeries, scopedKey } from "@/shared/lib/queryKeys";
import { useAuthStore } from "@/shared/state/auth-store";
import type { GenerateReportRequest } from "@/shared/types/reporting";

const REPORT_POLL_MS = 8_000;
const SETTLED_HISTORY_POLL_MS = 30_000;

export function useGenerateReport(token: string | null) {
  const client = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: {
      request: GenerateReportRequest;
      idempotencyKey: string;
    }) => {
      const credential = useAuthStore.getState().accessToken ?? token;
      if (!credential) {
        throw new Error("Authentication token is required.");
      }
      const response = await generateReport(credential, input.request, input.idempotencyKey);
      return response.data;
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: scopedKey(scope, "reports") }); },
  });
}

export function useReportHistory(token: string | null, workspaceId: string | null, page: number) {
  const scope = useSessionScope();
  const queryKey = scopedKey(scope, "reports", workspaceId, page);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await scope.read((credential) => listReports(credential, workspaceId as string, page, signal), signal)).data,
    enabled: Boolean(token && workspaceId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
    // Fast while a listed report is still generating; slow discovery of others' reports once all settled.
    refetchInterval: (query) => query.state.data?.items.every((report) => isReportTerminal(report.status)) ? SETTLED_HISTORY_POLL_MS : REPORT_POLL_MS,
  });
}

export function useReportDetail(token: string | null, reportId: string | null, workspaceId: string | null) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "report", reportId, workspaceId),
    queryFn: async ({ signal }) => (await scope.read((credential) => getReport(credential, reportId as string, workspaceId as string, signal), signal)).data,
    enabled: Boolean(token && reportId && workspaceId),
    // Terminal reports (generated/failed) no longer change: stop polling (item 9).
    refetchInterval: (query) => query.state.data && isReportTerminal(query.state.data.status) ? false : REPORT_POLL_MS,
  });
}

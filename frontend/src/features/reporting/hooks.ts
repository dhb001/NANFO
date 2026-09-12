import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { generateReport, getReport, listReports } from "@/features/reporting/api";
import { GenerateReportRequest } from "@/shared/types/reporting";

export function useGenerateReport(token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      request: GenerateReportRequest;
      idempotencyKey: string;
    }) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await generateReport(token, input.request, input.idempotencyKey);
      return response.data;
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ["reports", token] }); },
  });
}

export function useReportHistory(token: string | null, workspaceId: string | null, page: number) {
  return useQuery({
    queryKey: ["reports", token, workspaceId, page],
    queryFn: async () => (await listReports(token as string, workspaceId as string, page)).data,
    enabled: Boolean(token && workspaceId),
    refetchInterval: 8_000,
  });
}

export function useReportDetail(token: string | null, reportId: string | null, workspaceId: string | null) {
  return useQuery({
    queryKey: ["report", token, reportId, workspaceId],
    queryFn: async () => {
      const response = await getReport(token as string, reportId as string, workspaceId as string);
      return response.data;
    },
    enabled: Boolean(token && reportId && workspaceId),
    refetchInterval: 8_000,
  });
}

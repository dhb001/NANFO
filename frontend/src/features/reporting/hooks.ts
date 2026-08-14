import { useMutation, useQuery } from "@tanstack/react-query";

import { generateReport, getReport } from "@/features/reporting/api";
import { GenerateReportRequest } from "@/shared/types/reporting";

export function useGenerateReport(token: string | null) {
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

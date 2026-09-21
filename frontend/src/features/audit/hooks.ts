import { useQuery } from "@tanstack/react-query";
import { getAuditLogs } from "@/features/audit/api";
import { AuditLogParams } from "@/shared/types/audit";

export function useAuditLogs(token: string | null, orgId: string | null, options: Omit<AuditLogParams, "orgId"> = {}) {
  return useQuery({
    queryKey: ["audit", token, orgId, options],
    queryFn: async () => {
      const response = await getAuditLogs(token as string, { ...options, orgId: orgId ?? undefined });
      return response.data;
    },
    enabled: Boolean(token && orgId),
    refetchInterval: 15_000,
  });
}

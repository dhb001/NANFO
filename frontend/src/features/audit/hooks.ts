import { useQuery } from "@tanstack/react-query";
import { getAuditLogs } from "@/features/audit/api";

export function useAuditLogs(token: string | null, orgId: string | null) {
  return useQuery({
    queryKey: ["audit", token, orgId],
    queryFn: async () => {
      const response = await getAuditLogs(token as string, { orgId: orgId ?? undefined, pageSize: 120 });
      return response.data;
    },
    enabled: Boolean(token),
    refetchInterval: 15_000,
  });
}

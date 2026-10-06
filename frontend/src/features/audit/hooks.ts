import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getAuditLogs } from "@/features/audit/api";
import { useSessionScope } from "@/features/auth/sessionScope";
import { samePageSeries, scopedKey } from "@/shared/lib/queryKeys";
import type { AuditLogParams, AuditScope } from "@/shared/types/audit";

export function useAuditLogs(token: string | null, orgId: string | null, options: Omit<AuditLogParams, "orgId" | "scope"> = {}, scope: AuditScope = "org") {
  const session = useSessionScope();
  const { page, ...filters } = options;
  const queryKey = scopedKey(session, "audit", scope, scope === "org" ? orgId : null, filters, page ?? 1);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await session.read((credential) => getAuditLogs(credential, { ...options, scope, orgId: orgId ?? undefined }, signal), signal)).data,
    enabled: Boolean(token && (scope === "platform" || orgId)),
    refetchInterval: 15_000,
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 6) ? keepPreviousData(previous) : undefined,
  });
}

import { apiRequest } from "@/shared/lib/api";
import type { AuditLogList, AuditLogParams } from "@/shared/types/audit";

export function getAuditLogs(
  token: string,
  query: AuditLogParams,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams();
  if (query.scope === "platform") {
    // Platform scope cannot be combined with org_id (backend answers 422).
    params.set("scope", "platform");
  } else if (query.orgId) {
    params.set("org_id", query.orgId);
  }
  if (query.actorId) {
    params.set("actor_id", query.actorId);
  }
  if (query.resourceType) {
    params.set("resource_type", query.resourceType);
  }
  if (query.search) params.set("search", query.search);
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 50));

  return apiRequest<AuditLogList>(`/api/v1/audit/logs?${params.toString()}`, {
    token,
    signal,
  });
}

import { apiRequest } from "@/shared/lib/api";
import { AuditLogList } from "@/shared/types/audit";

export function getAuditLogs(
  token: string,
  query: { actorId?: string; orgId?: string; resourceType?: string; page?: number; pageSize?: number },
) {
  const params = new URLSearchParams();
  if (query.actorId) {
    params.set("actor_id", query.actorId);
  }
  if (query.orgId) {
    params.set("org_id", query.orgId);
  }
  if (query.resourceType) {
    params.set("resource_type", query.resourceType);
  }
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 50));

  return apiRequest<AuditLogList>(`/api/v1/audit/logs?${params.toString()}`, {
    token,
  });
}

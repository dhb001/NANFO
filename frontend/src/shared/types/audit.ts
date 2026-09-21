export interface AuditLogParams {
  actorId?: string;
  orgId?: string;
  resourceType?: string;
  search?: string;
  page?: number;
  pageSize?: number;
}

export interface AuditLogEntry {
  log_id: string;
  event_type: string;
  actor_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  org_id: string | null;
  correlation_id: string;
  timestamp: string;
  metadata: Record<string, unknown> | null;
}

export interface AuditLogList {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
}

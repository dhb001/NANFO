export interface AlertListParams {
  status?: "active" | "acknowledged" | "resolved";
  severity?: string;
  source?: string;
  correlationId?: string;
  search?: string;
  limit?: number;
  workspaceId?: string;
  networkId?: string;
}

export interface AlertRecord {
  alert_id: string;
  alert_key: string;
  source: string;
  status: string;
  severity: string | null;
  correlation_id: string;
  payload: Record<string, unknown>;
  acknowledged_by_user_id: string | null;
  resolved_by_user_id: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertListResult {
  items: AlertRecord[];
  /** Returned bounded matches, not a global or all-matches count. */
  total: number;
  status_counts: Record<string, number>;
}

export interface AlertActionResult extends AlertRecord {
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
  idempotent_replay: boolean;
}

export interface AlertHistoryResult {
  alert_id: string;
  items: { event_id: string; alert_id: string; event_type: string; correlation_id: string; occurred_at: string; payload: Record<string, unknown> }[];
  total: number;
}

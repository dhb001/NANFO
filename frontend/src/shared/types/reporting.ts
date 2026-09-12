export interface ReportDateRange {
  start: string;
  end: string;
}

export interface ReportArtifactRef {
  artifact_id: string;
  uri: string;
  media_type: string;
  checksum_sha256: string;
  size_bytes: number;
  generated_at: string;
  filename?: string | null;
}

export interface ReportErrorContext {
  code: string;
  message: string;
  [key: string]: unknown;
}

export interface ReportRecord {
  report_id: string;
  workspace_id: string;
  network_id: string | null;
  report_type: string;
  format: string;
  status: string;
  date_range: ReportDateRange;
  scope: Record<string, unknown>;
  filters: Record<string, unknown>;
  artifacts: ReportArtifactRef[];
  error: ReportErrorContext | null;
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
  idempotency_key: string | null;
  correlation_id: string;
  requested_by_user_id: string;
  requested_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  artifact_version?: number;
  status_version?: number;
  snapshot_sha256?: string | null;
  snapshot_summary?: Record<string, unknown>;
}

export interface ReportGenerateResult extends ReportRecord {
  idempotent_replay: boolean;
}

export interface GenerateReportRequest {
  workspace_id: string;
  network_id?: string | null;
  report_type: "executive_summary" | "operational_summary" | "telemetry" | "alerts" | "simulation" | "intent";
  format: "pdf" | "csv";
  date_range: ReportDateRange;
  scope: { workspace?: "all"; simulation_ids?: string[]; intent_ids?: string[] };
  filters: { metric?: string | null; alert_status?: "active" | "acknowledged" | "resolved" | null;
    alert_severity?: "info" | "warning" | "critical" | "low" | "medium" | "high" | null; max_rows?: number };
}

export interface ReportHistoryResult {
  items: ReportRecord[];
  total: number;
  page: number;
  page_size: number;
}

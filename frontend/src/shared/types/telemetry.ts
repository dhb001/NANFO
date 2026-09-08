export interface TelemetryRecord {
  record_id: string;
  event_id: string;
  correlation_id: string;
  device_id: string;
  network_id: string;
  workspace_id: string;
  metric: string;
  value: number;
  unit: string | null;
  observed_at: string;
  source: string;
  tags: Record<string, unknown>;
  created_at: string;
}

export interface TelemetryHistory {
  items: TelemetryRecord[];
  total: number;
  page: number;
  page_size: number;
}

export type TelemetryAggregation = "avg" | "min" | "max" | "sum";

export interface TelemetryAggregate {
  device_id: string;
  metric: string;
  unit: string | null;
  source: string;
  port_no: string | null;
  peer_host: string | null;
  run_id: string | null;
  bucket_start: string;
  value: number;
  sample_count: number;
}

export interface TelemetryAggregationHistory extends Omit<TelemetryHistory, "items"> {
  items: TelemetryAggregate[];
}

export interface TelemetryTimeRange {
  startTime?: string;
  endTime?: string;
}

export interface TelemetryHistoryQuery extends TelemetryTimeRange {
  networkId?: string;
  workspaceId?: string;
  metric?: string;
  page?: number;
  pageSize?: number;
  aggregation?: TelemetryAggregation;
  bucketSeconds?: number;
}

export interface TelemetryDeviceHistory {
  device_id: string;
  items: TelemetryRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface TelemetryHealth {
  status: string;
  ingest_lag_ms: number | null;
  dropped_events: number;
  latest_observed_at: string | null;
  total_records: number;
}

export interface TelemetryMetricDelta {
  event_id: string;
  device_id: string;
  network_id: string;
  workspace_id: string;
  metric: string;
  value: number;
  unit: string | null;
  observed_at: string;
  source: string;
  tags: Record<string, unknown>;
}

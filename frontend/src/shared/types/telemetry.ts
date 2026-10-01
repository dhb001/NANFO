import type { Schema } from "@/shared/types/contracts";

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
  /** `total` stopped counting at the server cap: present it as "≥ total" (C12). */
  total_capped?: boolean;
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
  startTime?: string | undefined;
  endTime?: string | undefined;
}

export interface TelemetryHistoryQuery extends TelemetryTimeRange {
  networkId?: string | undefined;
  workspaceId?: string | undefined;
  metric?: string | undefined;
  page?: number | undefined;
  pageSize?: number | undefined;
  aggregation?: TelemetryAggregation | undefined;
  bucketSeconds?: number | undefined;
}

export interface TelemetryDeviceHistory {
  device_id: string;
  items: TelemetryRecord[];
  total: number;
  page: number;
  page_size: number;
  total_capped?: boolean;
}

/** Collector-evaluated SLO state (read-only, ADR-028 C12). */
export type TelemetrySloHealth = Schema<"TelemetrySLOHealth">;

export interface TelemetryHealth {
  status: string;
  ingest_lag_ms: number | null;
  dropped_events: number;
  latest_observed_at: string | null;
  total_records: number;
  /** `total_records` is a planner estimate, not an exact count. */
  total_records_estimated?: boolean;
  slo?: TelemetrySloHealth | null;
}

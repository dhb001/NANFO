// backend/app/modules/telemetry/paths.py: public ProbePathsResponse projection.
export interface ProbePath {
  packet_id: string; icmp_id: number; icmp_seq: number;
  src_host: "h1"; dst_host: "h3"; src_ip: "10.77.0.1"; dst_ip: "10.77.0.3";
  source_timestamp: string | null; destination_timestamp: string | null;
  source_device_id: string; destination_device_id: string;
  status: "measured" | "partial" | "ambiguous"; captured_packet_count: number;
  observed_hops: { dpid: string; device_id: string; ingress_port: number | null; egress_port: number | null;
    received_at: string | null; sent_at: string | null }[];
}
export interface ProbePaths {
  network_id: string; workspace_id: string;
  status: "measured" | "partial" | "ambiguous" | "stale" | "unavailable" | "invalid" | "run_mismatch";
  reason: string | null; scope: "selected_probe_only"; freshness: "fresh" | "stale" | "unavailable";
  run_id: string | null; window_id: string | null; window_start: string | null; window_end: string | null;
  age_seconds: number | null; max_age_seconds: number; evidence_sha256: string | null;
  evidence_verification: "raw_pcap_replayed" | null; captured_packet_count: number; measured_path_count: number;
  paths: ProbePath[]; configuration_comparison: "unavailable";
  path_variation: "single_observed_path" | "multiple_observed_paths" | "unknown";
}

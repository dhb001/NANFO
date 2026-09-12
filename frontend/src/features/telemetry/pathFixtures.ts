import type { ProbePaths } from "./pathTypes";
export function pathsFixture(now = Date.now()): ProbePaths {
  return { network_id: "00000000-0000-0000-0000-000000000333", workspace_id: "00000000-0000-0000-0000-000000000222",
    status: "measured", reason: null, scope: "selected_probe_only", freshness: "fresh", path_variation: "single_observed_path",
    run_id: "30000000-0000-4000-8000-000000000001", window_id: "30000000-0000-4000-8000-000000000002",
    window_start: new Date(now - 2000).toISOString(), window_end: new Date(now - 1000).toISOString(), age_seconds: 1, max_age_seconds: 30,
    evidence_sha256: "a".repeat(64), evidence_verification: "raw_pcap_replayed", captured_packet_count: 12, measured_path_count: 3, configuration_comparison: "unavailable",
    paths: [1, 2, 3].map((sequence) => ({ packet_id: `probe-${sequence}`, icmp_id: 42, icmp_seq: sequence,
      src_host: "h1", dst_host: "h3", src_ip: "10.77.0.1", dst_ip: "10.77.0.3",
      source_timestamp: new Date(now - 1800).toISOString(), destination_timestamp: new Date(now - 1200).toISOString(),
      source_device_id: "30000000-0000-4000-8000-000000000003", destination_device_id: "30000000-0000-4000-8000-000000000004", status: "measured", captured_packet_count: 4,
      observed_hops: [{ device_id: "30000000-0000-4000-8000-000000000005", dpid: "0000000000000001", ingress_port: 1, egress_port: 2,
        received_at: new Date(now - 1600).toISOString(), sent_at: new Date(now - 1400).toISOString() }] })) };
}

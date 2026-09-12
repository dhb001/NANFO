import { apiRequest } from "@/shared/lib/api";
import { ApiClientError } from "@/shared/lib/errors";
import type { ProbePaths } from "./pathTypes";

const time = (value: unknown) => value === null || (typeof value === "string" && Number.isFinite(Date.parse(value)));
const uuid = (value: unknown) => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const integer = (value: number, min: number, max: number) => Number.isInteger(value) && value >= min && value <= max;
export async function getProbePaths(token: string, networkId: string, workspaceId: string, signal?: AbortSignal) {
  const { data } = await apiRequest<ProbePaths>(`/api/v1/telemetry/paths?${new URLSearchParams({ network_id: networkId })}`, { token, signal });
  if (data.network_id !== networkId || data.workspace_id !== workspaceId || data.scope !== "selected_probe_only" ||
      !["measured", "partial", "ambiguous", "stale", "unavailable", "invalid", "run_mismatch"].includes(data.status) ||
      !["fresh", "stale", "unavailable"].includes(data.freshness) || !(data.reason === null || typeof data.reason === "string") ||
      ![data.run_id, data.window_id].every((value) => value === null || uuid(value)) || ![data.window_start, data.window_end].every(time) ||
      !(data.age_seconds === null || (Number.isFinite(data.age_seconds) && data.age_seconds >= 0)) ||
      !Number.isFinite(data.max_age_seconds) || data.max_age_seconds <= 0 || data.max_age_seconds > 30 ||
      !(data.evidence_sha256 === null || /^[a-f0-9]{64}$/.test(data.evidence_sha256)) ||
      !(data.evidence_verification === null || data.evidence_verification === "raw_pcap_replayed") || data.configuration_comparison !== "unavailable" ||
      !["single_observed_path", "multiple_observed_paths", "unknown"].includes(data.path_variation) ||
      !integer(data.captured_packet_count, 0, 512) || !integer(data.measured_path_count, 0, 3) || !Array.isArray(data.paths) || data.paths.length > 3 ||
      !data.paths.every((path) => path && typeof path.packet_id === "string" && path.packet_id.length <= 48 && integer(path.icmp_id, 1, 65535) && integer(path.icmp_seq, 1, 3) &&
        path.src_host === "h1" && path.dst_host === "h3" && path.src_ip === "10.77.0.1" && path.dst_ip === "10.77.0.3" &&
        [path.source_device_id, path.destination_device_id].every(uuid) && [path.source_timestamp, path.destination_timestamp].every(time) &&
        ["measured", "partial", "ambiguous"].includes(path.status) && integer(path.captured_packet_count, 0, 512) &&
        Array.isArray(path.observed_hops) && path.observed_hops.length <= 64 && path.observed_hops.every((hop) => hop && uuid(hop.device_id) &&
          typeof hop.dpid === "string" && /^[a-f0-9]{16}$/.test(hop.dpid) &&
          [hop.ingress_port, hop.egress_port].every((port) => port === null || integer(port, 0, 65535)) && [hop.received_at, hop.sent_at].every(time)))) {
    throw new ApiClientError("Probe paths are incompatible or outside the selected scope. No path highlight is authorized.", "PATH_INVALID_RESPONSE");
  }
  if (data.freshness === "fresh" && (!data.window_start || !data.window_end || !data.run_id || !data.window_id ||
      !data.evidence_sha256 || data.evidence_verification !== "raw_pcap_replayed" || data.age_seconds === null ||
      Date.parse(data.window_start) >= Date.parse(data.window_end) || data.paths.length !== 3)) {
    throw new ApiClientError("Fresh probe evidence is incomplete.", "PATH_INVALID_RESPONSE");
  }
  return data;
}

export function probeEvidenceFresh(data: ProbePaths, readAt: number, now: number) {
  if (data.freshness !== "fresh" || !data.window_start || !data.window_end || data.age_seconds === null) return false;
  const windowMs = Date.parse(data.window_end) - Date.parse(data.window_start);
  // Age at read includes the entire capture window; local clock never renews server freshness.
  return now >= readAt && windowMs > 0 && data.age_seconds * 1000 + windowMs + now - readAt < data.max_age_seconds * 1000;
}

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { hasPermission } from "@/features/auth/permissions";
import { getProbePaths, probeEvidenceFresh } from "@/features/telemetry/pathApi";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { toErrorMessage } from "@/shared/lib/errors";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { mapMeasuredPath, type MeasuredPathSegment } from "./measuredPathMapping";
import type { TwinLink, TwinNode } from "./sceneAdapter";

export function MeasuredPathPanel({ nodes, links, onHighlight }: {
  nodes: readonly TwinNode[]; links: readonly TwinLink[]; onHighlight: (segments: MeasuredPathSegment[] | null) => void;
}) {
  const auth = useAuthStore();
  const scope = useWorkspaceStore();
  const canRead = hasPermission(auth.profile, "read:telemetry");
  const enabled = Boolean(canRead && auth.accessToken && !auth.endingSession && scope.networkId && scope.workspaceId && scope.organizationId);
  const [now, setNow] = useState(Date.now());
  const [selected, setSelected] = useState("");
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const query = useQuery({ queryKey: ["probe-paths", auth.generation, auth.accessToken, auth.profile?.permissions, scope.organizationId, scope.workspaceId, scope.networkId],
    queryFn: ({ signal }) => {
      if (!enabled) throw new Error("Current network scope and read:telemetry are required.");
      return getProbePaths(auth.accessToken!, scope.networkId!, scope.workspaceId!, signal);
    }, enabled: false, retry: false, gcTime: 0, refetchOnWindowFocus: false });
  const data = query.data;
  const fresh = Boolean(enabled && query.isSuccess && !query.isFetching && data && probeEvidenceFresh(data, query.dataUpdatedAt, now));
  const path = data?.paths.find((item) => item.packet_id === selected);
  useEffect(() => {
    // The current public contract has node IDs but no canonical link IDs. Never synthesize them.
    const ids = path ? [path.source_device_id, ...path.observed_hops.map((hop) => hop.device_id), path.destination_device_id] : [];
    onHighlight(fresh && path?.status === "measured" ? mapMeasuredPath(ids, ids.slice(1).map(() => null), nodes, links) : null);
    return () => onHighlight(null);
  }, [fresh, path, nodes, links, onHighlight]);
  return <Panel title="Measured probe paths" subtitle="Actual selected-probe capture, separate from approved configuration">
    <div style={{ display: "grid", gap: "0.7rem", overflowWrap: "anywhere", minWidth: 0 }}>
      <p>Observed paths apply only to selected probes during their measured window, not all application flows or an indefinitely active path.</p>
      <Button tone="ghost" disabled={!enabled || query.isFetching} onClick={() => void query.refetch()}>{query.isFetching ? "Refreshing measured paths..." : "Refresh measured paths"}</Button>
      {!canRead && <p>Permission denied: measured paths require read:telemetry. No request is made.</p>}
      {canRead && !enabled && <p>Select a current organization, workspace and network.</p>}
      {!data && !query.isFetching && !query.isError && <p>No probe evidence loaded. Refresh explicitly; no capture or control action is requested.</p>}
      {query.isFetching && <p role="status">Reading measured paths. Previous evidence does not drive highlights.</p>}
      {query.isError && <p role="alert">Measured paths unavailable. {toErrorMessage(query.error)} Retry with Refresh measured paths. Last-known evidence is not current.</p>}
      {data && <>
        <p>Server status: <strong>{data.status}</strong>. Server freshness at read: {data.freshness}. Current evidence: <strong>{fresh ? "fresh window" : "stale or unavailable"}</strong>.</p>
        {data.reason && <p>{data.reason}</p>}
        <p>Run: {data.run_id ?? "unavailable"}. Window: {data.window_id ?? "unavailable"}.</p>
        <p>Measured window: {data.window_start ?? "unavailable"} to {data.window_end ?? "unavailable"}. Age at read: {data.age_seconds ?? "unknown"}s; maximum age {data.max_age_seconds}s.</p>
        <p>Captured packets: {data.captured_packet_count}. Complete measured probe paths: {data.measured_path_count}.</p>
        <p>Observed path variation: {data.path_variation}. Different probes may take different paths.</p>
        <p className="mono">Evidence SHA-256: {data.evidence_sha256 ?? "unavailable"}. Verification: {data.evidence_verification ?? "unavailable"}.</p>
        {!data.paths.length ? <p>No observed hops available. No route is reconstructed from a planned configuration.</p> : <>
          <label>Selected measured probe<select aria-label="Selected measured probe" value={selected} onChange={(event) => setSelected(event.target.value)} style={{ width: "100%", minWidth: 0 }}>
            <option value="">Select a recorded probe</option>{data.paths.map((item) => <option key={item.packet_id} value={item.packet_id}>{item.packet_id} ({item.status})</option>)}
          </select></label>
          {path && <section aria-label="Ordered observed probe hops">
            <h4>Probe {path.packet_id}: {path.status}</h4><p>ICMP ID {path.icmp_id}, sequence {path.icmp_seq}. {path.src_ip} to {path.dst_ip}.</p>
            <p>Source canonical ID: {path.source_device_id} at {path.source_timestamp ?? "not observed"}.</p>
            <ol>{path.observed_hops.map((hop, i) => <li key={`${i}:${hop.device_id}`}>Canonical ID {hop.device_id}; DPID {hop.dpid}; ingress {hop.ingress_port ?? "unknown"} to egress {hop.egress_port ?? "unknown"}. Received {hop.received_at ?? "unknown"}; sent {hop.sent_at ?? "unknown"}.</li>)}</ol>
            <p>Destination canonical ID: {path.destination_device_id} at {path.destination_timestamp ?? "not observed"}.</p>
            <p>List fallback: canonical link IDs are not supplied by this provider. Unknown or unmatched scene identities are never guessed. No arrow highlight is shown.</p>
            {path.status !== "measured" && <p>Partial or ambiguous evidence does not establish a complete ordered path.</p>}
          </section>}
        </>}
        <section aria-label="Approved configuration comparison"><h4>Approved configuration (separate)</h4>
          <p>Comparison: {data.configuration_comparison}. View the selected Intent's persisted approved plan and configuration readback separately. They are not measured traversal.</p></section>
      </>}
    </div>
  </Panel>;
}

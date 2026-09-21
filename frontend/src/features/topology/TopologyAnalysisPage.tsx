import { useEffect, useMemo, useRef, useState } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { QueryState } from "@/shared/ui/QueryState";
import { Badge } from "@/shared/ui/Badge";
import { AsyncState } from "@/shared/ui/AsyncState";
import { useLiveStore } from "@/features/realtime/store";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { formatTimestamp } from "@/shared/lib/format";
import { toErrorMessage } from "@/shared/lib/errors";
import {
  useTopologyGraph,
  useReconcileTopology,
  useTopologyImpact,
  useTopologyNeighbours,
} from "@/features/topology/hooks";
import {
  sanitizeRangeInput,
  summarizeImpactStats,
  summarizeNeighbourStats,
} from "@/features/topology/logic";

type TopologyTab = "neighbours" | "impact";

function statusTone(status: string): "neutral" | "ok" | "warn" | "danger" | "info" {
  if (status === "active") {
    return "ok";
  }
  if (status === "offline") {
    return "warn";
  }
  if (status === "deleted") {
    return "danger";
  }
  return "neutral";
}

export function TopologyAnalysisPage() {
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const isNarrowViewport = useIsNarrowViewport();

  const graphQuery = useTopologyGraph(token, networkId);
  const liveTopologyStatus = useLiveStore((state) => state.topologyStatus);

  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [depth, setDepth] = useState(2);
  const [maxHops, setMaxHops] = useState(3);
  const [activeTab, setActiveTab] = useState<TopologyTab>("neighbours");
  const [lastRealtimeInvalidationAt, setLastRealtimeInvalidationAt] = useState<string | null>(null);
  const lastLiveDeltaFingerprintRef = useRef<string>("");

  const boundedDepth = sanitizeRangeInput(depth, 1, 6);
  const boundedMaxHops = sanitizeRangeInput(maxHops, 1, 8);

  const neighboursQuery = useTopologyNeighbours(token, selectedDeviceId, boundedDepth, 200);
  const impactQuery = useTopologyImpact(token, selectedDeviceId, boundedMaxHops, 500);
  const reconcileMutation = useReconcileTopology(token, networkId);
  const refetchNeighbours = neighboursQuery.refetch;
  const refetchImpact = impactQuery.refetch;

  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);
  const liveDeltaFingerprint = useMemo(() => {
    const keys = Object.keys(topologyByDeviceId).sort();
    if (keys.length === 0) {
      return "";
    }
    return keys
      .map((key) => {
        const node = topologyByDeviceId[key];
        return `${key}:${node.status ?? ""}:${node.device_type ?? ""}`;
      })
      .join("|");
  }, [topologyByDeviceId]);

  useEffect(() => {
    if (!selectedDeviceId) {
      return;
    }
    if (!liveDeltaFingerprint) {
      return;
    }

    if (lastLiveDeltaFingerprintRef.current === liveDeltaFingerprint) {
      return;
    }

    lastLiveDeltaFingerprintRef.current = liveDeltaFingerprint;

    refetchNeighbours();
    refetchImpact();
    setLastRealtimeInvalidationAt(new Date().toISOString());
  }, [
    liveDeltaFingerprint,
    refetchImpact,
    refetchNeighbours,
    selectedDeviceId,
  ]);

  const selectableDevices = useMemo(() => {
    const baseNodes = graphQuery.data?.data.nodes ?? [];
    return [...baseNodes].sort((left, right) => left.hostname.localeCompare(right.hostname));
  }, [graphQuery.data?.data.nodes]);

  useEffect(() => {
    if (!selectedDeviceId && selectableDevices.length > 0) {
      setSelectedDeviceId(selectableDevices[0].device_id);
    }
  }, [selectableDevices, selectedDeviceId]);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel
        title="Topology Analysis"
        subtitle="Inspect neighboring devices, trace dependencies and reconcile topology"
        action={
          <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
            <Badge text={`topology ws ${liveTopologyStatus}`} tone={liveTopologyStatus === "open" ? "ok" : "warn"} />
            {lastRealtimeInvalidationAt ? (
              <Badge text={`refreshed ${formatTimestamp(lastRealtimeInvalidationAt)}`} tone="info" />
            ) : null}
          </div>
        }
      >
        <QueryState
          query={graphQuery}
          hasData={(data) => data.data.nodes.length > 0}
          emptyTitle="No topology devices"
          emptyDescription="Select a network and add devices before running topology analysis."
        >
          {() => (
            <div style={{ display: "grid", gap: "0.7rem" }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: isNarrowViewport ? "1fr" : "2fr 1fr 1fr auto",
                  gap: "0.55rem",
                  alignItems: "end",
                }}
              >
                <label style={{ display: "grid", gap: "0.3rem" }}>
                  <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                    Device
                  </span>
                  <select
                    aria-label="Topology analysis device"
                    value={selectedDeviceId ?? ""}
                    onChange={(event) => setSelectedDeviceId(event.target.value || null)}
                    style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
                  >
                    {selectableDevices.map((node) => (
                      <option key={node.device_id} value={node.device_id}>
                        {node.hostname} ({node.device_type})
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ display: "grid", gap: "0.3rem" }}>
                  <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                    Neighbour depth
                  </span>
                  <input
                    aria-label="Neighbour depth"
                    type="number"
                    min={1}
                    max={6}
                    value={depth}
                    onChange={(event) => setDepth(sanitizeRangeInput(Number(event.target.value), 1, 6))}
                    style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
                  />
                </label>

                <label style={{ display: "grid", gap: "0.3rem" }}>
                  <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                    Impact max hops
                  </span>
                  <input
                    aria-label="Impact max hops"
                    type="number"
                    min={1}
                    max={8}
                    value={maxHops}
                    onChange={(event) => setMaxHops(sanitizeRangeInput(Number(event.target.value), 1, 8))}
                    style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
                  />
                </label>

                <Button
                  permission="write:config"
                  type="button"
                  tone="ghost"
                  disabled={!networkId || reconcileMutation.isPending}
                  onClick={() => reconcileMutation.mutate()}
                >
                  {reconcileMutation.isPending ? "Reconciling..." : "Run Reconcile"}
                </Button>
              </div>

              {reconcileMutation.isError ? (
                <AsyncState title="Reconcile failed" description={toErrorMessage(reconcileMutation.error)} />
              ) : null}

              {reconcileMutation.data ? (
                <div
                  style={{
                    border: "1px solid var(--line-soft)",
                    borderRadius: "10px",
                    padding: "0.45rem 0.5rem",
                    display: "grid",
                    gap: "0.28rem",
                  }}
                >
                  <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                    <Badge text={`reconcile ${reconcileMutation.data.status}`} tone="ok" />
                    <Badge text={`nodes ${reconcileMutation.data.checked_nodes}`} tone="info" />
                    <Badge text={`edges ${reconcileMutation.data.checked_edges}`} tone="info" />
                    <Badge text={`backfilled ${reconcileMutation.data.workspace_backfilled_nodes}`} tone="warn" />
                    {reconcileMutation.data.warning ? <Badge text={reconcileMutation.data.warning} tone="warn" /> : null}
                  </div>
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                    reconcile_id: {reconcileMutation.data.reconcile_id}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </QueryState>
      </Panel>

      <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
        <Button type="button" tone={activeTab === "neighbours" ? "primary" : "ghost"} onClick={() => setActiveTab("neighbours")}>
          Neighbours
        </Button>
        <Button type="button" tone={activeTab === "impact" ? "primary" : "ghost"} onClick={() => setActiveTab("impact")}>
          Impact
        </Button>
      </div>

      {activeTab === "neighbours" ? (
        <Panel title="Neighbour Analysis" subtitle="Direct connections and link details for the selected device">
          <QueryState
            query={neighboursQuery}
            hasData={(data) => data.neighbours.length > 0}
            emptyTitle="No neighbours reachable"
            emptyDescription="No reachable neighbours for selected node and depth."
          >
            {(data) => (
              <div style={{ display: "grid", gap: "0.4rem" }}>
                {(() => {
                  const summary = summarizeNeighbourStats(data);
                  return (
                    <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                      <Badge text={`device ${data.device.hostname}`} tone="info" />
                      <Badge text={`depth ${data.depth}`} tone="info" />
                      <Badge text={`total ${summary.total}`} tone="ok" />
                      {Object.entries(summary.byHopDepth).map(([hopDepth, count]) => (
                        <Badge key={`hop-summary-${hopDepth}`} text={`hop ${hopDepth}: ${count}`} tone="warn" />
                      ))}
                    </div>
                  );
                })()}
                {data.neighbours.map((item) => (
                  <div
                    key={`${item.device_id}:${item.direction}:${item.hop_depth}`}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "9px",
                      padding: "0.44rem 0.48rem",
                      display: "grid",
                      gap: "0.2rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem", alignItems: "center" }}>
                      <strong>{item.hostname}</strong>
                      <Badge text={item.status} tone={statusTone(item.status)} />
                    </div>
                    <div style={{ display: "flex", gap: "0.32rem", flexWrap: "wrap" }}>
                      <Badge text={`${item.direction} ${item.edge_type}`} tone="warn" />
                      <Badge text={`hop ${item.hop_depth}`} tone="info" />
                    </div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      {item.device_id}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </QueryState>
        </Panel>
      ) : (
        <Panel title="Impact Analysis" subtitle="Reachable dependencies and their distance from the selected device">
          <QueryState
            query={impactQuery}
            hasData={(data) => data.impacts.length > 0}
            emptyTitle="No impacted dependencies"
            emptyDescription="No impacted nodes reachable for selected node and max hops."
          >
            {(data) => (
              <div style={{ display: "grid", gap: "0.4rem" }}>
                {(() => {
                  const summary = summarizeImpactStats(data);
                  return (
                    <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                      <Badge text={`device ${data.device.hostname}`} tone="info" />
                      <Badge text={`max_hops ${data.max_hops}`} tone="info" />
                      <Badge text={`total ${summary.total}`} tone="ok" />
                      {Object.entries(summary.byHopDepth).map(([hopDepth, count]) => (
                        <Badge key={`impact-hop-summary-${hopDepth}`} text={`hop ${hopDepth}: ${count}`} tone="warn" />
                      ))}
                    </div>
                  );
                })()}
                {data.impacts.map((item) => (
                  <div
                    key={`${item.device_id}:${item.hop_depth}`}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "9px",
                      padding: "0.44rem 0.48rem",
                      display: "grid",
                      gap: "0.2rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem", alignItems: "center" }}>
                      <strong>{item.hostname}</strong>
                      <Badge text={item.status} tone={statusTone(item.status)} />
                    </div>
                    <div style={{ display: "flex", gap: "0.32rem", flexWrap: "wrap" }}>
                      <Badge text={`hop ${item.hop_depth}`} tone="warn" />
                      <Badge text={item.device_type} tone="info" />
                    </div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      {item.device_id}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </QueryState>
        </Panel>
      )}
    </div>
  );
}

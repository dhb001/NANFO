import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { intentHandoffState } from "@/features/intent/handoff";
import { useUpdateDeviceSpatialRef } from "@/features/networks/hooks";
import { useTopologyNode } from "@/features/topology/hooks";
import { useUiStore } from "@/shared/state/ui-store";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { MetricSnapshotList } from "./MetricSnapshotList";
import { VirtualizedNodeCombobox } from "./VirtualizedNodeCombobox";
import { nodeComboboxOptions } from "./comboboxWindow";
import { buildIntentHandoffFromNode } from "./intentHandoff";
import type { TwinCongestion, TwinNode } from "./sceneAdapter";
import { deviceStatusTone } from "./twinStatusTones";
import { HEURISTIC_LEVEL_TEXT, VISUAL_HEURISTIC_LABEL, describeDeviceAlerts, type DeviceAlertSummary } from "./twinSeverity";

function useSpatialRefPersistence(token: string | null, networkId: string | null) {
  const mutation = useUpdateDeviceSpatialRef(token, networkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const persist = useCallback(async (node: TwinNode) => {
    if (!node.spatialRefId || !token || !networkId) return;
    setPendingId(node.id);
    try {
      await mutation.mutateAsync({ deviceId: node.id, spatialRefId: node.spatialRefId });
      pushToast({ tone: "ok", title: "Spatial mapping persisted", description: `${node.hostname} now uses spatial_ref_id ${node.spatialRefId}.` });
    } catch (error) {
      pushToast({ tone: "danger", title: "Spatial mapping persist failed", description: error instanceof Error ? error.message : "Could not persist spatial mapping." });
    } finally {
      setPendingId(null);
    }
  }, [mutation, networkId, pushToast, token]);
  return { pendingId, persist };
}

function SelectedNodeCard({ node, congestion, alerts, sessionRef, token, networkId }: {
  node: TwinNode;
  congestion: TwinCongestion;
  alerts: DeviceAlertSummary | undefined;
  sessionRef: string | null;
  token: string | null;
  networkId: string | null;
}) {
  const navigate = useNavigate();
  const { pendingId, persist } = useSpatialRefPersistence(token, networkId);
  const persisted = node.persistedSpatialRefId ?? null;
  const hasSessionRef = Boolean(sessionRef);
  const canPersist = hasSessionRef && Boolean(node.spatialRefId) && node.spatialRefId !== persisted && Boolean(token && networkId);
  const sample = congestion.metrics[0];
  return (
    <div className="twin-stack twin-stack--tight">
      <div className="twin-card">
        <strong>{node.hostname}</strong>
        <div className="mono twin-meta">{node.id}</div>
        <div className="twin-badges">
          <Badge text={node.type} tone="info" />
          <Badge text={node.status} tone={deviceStatusTone(node.status)} />
          <Badge text={describeDeviceAlerts(alerts)} tone={alerts?.status === "active" ? "danger" : alerts ? "warn" : "neutral"} />
        </div>
        <div className="mono twin-meta">spatial_ref_id: {node.spatialRefId ?? "none"}</div>
        <div>Position: {node.placementSource === "canonical" ? `canonical (${node.spatialObjectId})` : "schematic fallback"} · ({node.x.toFixed(2)}, {node.y.toFixed(2)}, {node.z.toFixed(2)}) m</div>
        <div className="twin-badges">
          <Badge text={persisted ? "persisted" : "not persisted"} tone={persisted ? "ok" : "warn"} />
          {hasSessionRef ? <Badge text="session import" tone="warn" /> : null}
        </div>
        <div className="mono twin-meta">
          {VISUAL_HEURISTIC_LABEL}: {sample && !sample.stale ? `${sample.metric} ${HEURISTIC_LEVEL_TEXT[sample.level]}` : "no current detector-covered sample"} (not an alert)
        </div>
      </div>
      <MetricSnapshotList metrics={congestion.metrics} />
      {hasSessionRef ? (
        <Button type="button" tone="ghost" permission="write:config" disabled={!canPersist || pendingId === node.id} onClick={() => void persist(node)}>
          {pendingId === node.id ? "Persisting mapping..." : "Persist Mapping to Device"}
        </Button>
      ) : null}
      {/* Router state, not the URL: the handoff never lands in history exports, logs or referrers. */}
      <Button permission="write:config" type="button" tone="ghost"
        onClick={() => navigate("/ops/intent", { state: intentHandoffState(buildIntentHandoffFromNode(node, alerts?.alerts ?? [])) })}>
        Configure in Intent Workflow
      </Button>
    </div>
  );
}

/** Device inspector with the keyboard-accessible node picker (alternative to 3D selection). */
export function TwinInspectorPanel({ token, networkId, nodes, selectedNode, selectedNodeId, onSelectNode, congestion, alerts, sessionRef }: {
  token: string | null;
  networkId: string | null;
  nodes: readonly TwinNode[];
  selectedNode: TwinNode | null;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  congestion: TwinCongestion;
  alerts: DeviceAlertSummary | undefined;
  sessionRef: string | null;
}) {
  const options = useMemo(() => nodeComboboxOptions(nodes), [nodes]);
  const nodeQuery = useTopologyNode(token, selectedNodeId);
  return (
    <Panel title="Inspector" subtitle="Device identity, topology, spatial reference, and congestion">
      <VirtualizedNodeCombobox label="Inspect Node" ariaLabel="Inspect node" options={options} selectedId={selectedNodeId} onSelect={onSelectNode} />
      {selectedNode ? (
        <SelectedNodeCard key={selectedNode.id} node={selectedNode} congestion={congestion} alerts={alerts} sessionRef={sessionRef} token={token} networkId={networkId} />
      ) : null}
      <QueryState query={nodeQuery} emptyTitle="Select a node" emptyDescription="Pick a device with Inspect node, or click it in the 3D view, to inspect its topology neighbours.">
        {(nodeData) => (
          <ul className="twin-card-list" aria-label="Topology neighbours">
            {nodeData.neighbours.map((neighbour) => (
              <li key={`${neighbour.device_id}-${neighbour.direction}`} className="twin-card twin-card--compact">
                <div className="twin-row">
                  <span>{neighbour.hostname}</span>
                  <Badge text={neighbour.direction} tone={neighbour.direction === "inbound" ? "warn" : "ok"} />
                </div>
                <div className="mono twin-meta">{neighbour.device_id}</div>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Panel>
  );
}

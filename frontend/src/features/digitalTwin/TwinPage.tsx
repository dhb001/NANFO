import { useMemo, useState } from "react";
import { TwinScene } from "@/features/digitalTwin/TwinScene";
import { useTwinLinks, useTwinNodes } from "@/features/digitalTwin/hooks";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { useTopologyGraph, useTopologyNode } from "@/features/topology/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { Badge } from "@/shared/ui/Badge";
import { usePrefersReducedMotion } from "@/shared/lib/reduced-motion";
import { useIsNarrowViewport } from "@/shared/lib/viewport";

export function TwinPage() {
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);

  const graphQuery = useTopologyGraph(token, networkId);
  const baseGraph = graphQuery.data?.data;
  const twinNodes = useTwinNodes(baseGraph?.nodes ?? []);
  const twinLinks = useTwinLinks(twinNodes, baseGraph?.edges ?? []);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const isNarrowViewport = useIsNarrowViewport();

  const topologyStatus = useLiveStore((state) => state.topologyStatus);
  const digitalTwinStatus = useLiveStore((state) => state.digitalTwinStatus);
  const sceneObjects = useLiveStore((state) => state.sceneObjects);

  const nodeQuery = useTopologyNode(token, selectedNodeId);

  const liveSceneCards = useMemo(() => Object.values(sceneObjects).slice(0, 8), [sceneObjects]);
  const inspectorNodes = useMemo(() => {
    return twinNodes
      .map((node) => ({ id: node.id, label: `${node.hostname} (${node.type})` }))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [twinNodes]);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel
        title="3D Digital Twin"
        subtitle="Interactive topology scene with websocket-driven deltas"
        action={
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Badge text={`topology ${topologyStatus}`} tone={topologyStatus === "open" ? "ok" : "warn"} />
            <Badge text={`digital twin ${digitalTwinStatus}`} tone={digitalTwinStatus === "open" ? "ok" : "warn"} />
          </div>
        }
      >
        <QueryState
          query={graphQuery}
          hasData={(data) => data.data.nodes.length > 0 || twinNodes.length > 0}
          emptyTitle="Topology graph is empty"
          emptyDescription="Add devices and wait for topology websocket deltas."
        >
          {() => (
            <TwinScene
              nodes={twinNodes}
              links={twinLinks}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              reducedMotion={prefersReducedMotion}
            />
          )}
        </QueryState>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Inspector" subtitle="Node details + one-hop neighbours from /topology/nodes/{id}">
          <label style={{ display: "grid", gap: "0.3rem", marginBottom: "0.7rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
              Inspect Node
            </span>
            <select
              aria-label="Inspect node"
              value={selectedNodeId ?? ""}
              onChange={(event) => setSelectedNodeId(event.target.value || null)}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
            >
              <option value="">Select node</option>
              {inspectorNodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.label}
                </option>
              ))}
            </select>
          </label>
          <QueryState
            query={nodeQuery}
            emptyTitle="Select a node"
            emptyDescription="Click a 3D object to inspect topology neighbours."
          >
            {(nodeData) => (
              <div style={{ display: "grid", gap: "0.45rem" }}>
                <div style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.5rem" }}>
                  <strong>{nodeData.node.hostname}</strong>
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                    {nodeData.node.device_id}
                  </div>
                  <div style={{ marginTop: "0.2rem", display: "flex", gap: "0.35rem" }}>
                    <Badge text={nodeData.node.device_type} tone="info" />
                    <Badge text={nodeData.node.status} tone={nodeData.node.status === "active" ? "ok" : "warn"} />
                  </div>
                </div>

                <div style={{ display: "grid", gap: "0.32rem", maxHeight: 260, overflow: "auto" }}>
                  {nodeData.neighbours.map((neighbour) => (
                    <div
                      key={`${neighbour.device_id}-${neighbour.direction}`}
                      style={{ border: "1px solid var(--line-soft)", borderRadius: "9px", padding: "0.4rem 0.45rem" }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem" }}>
                        <span>{neighbour.hostname}</span>
                        <Badge text={neighbour.direction} tone={neighbour.direction === "inbound" ? "warn" : "ok"} />
                      </div>
                      <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                        {neighbour.device_id}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel title="Live Scene Deltas" subtitle="simulation.* and intent.* mapped on /ws/digital-twin">
          {liveSceneCards.length === 0 ? (
            <div style={{ color: "var(--ink-3)" }}>No scene deltas observed yet.</div>
          ) : (
            <div style={{ display: "grid", gap: "0.36rem" }}>
              {liveSceneCards.map((sceneObject) => (
                <div
                  key={sceneObject.id}
                  style={{ border: "1px solid var(--line-soft)", borderRadius: "9px", padding: "0.45rem 0.48rem" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.45rem" }}>
                    <strong>{sceneObject.id}</strong>
                    <Badge text={sceneObject.object_type} tone="info" />
                  </div>
                  {sceneObject.status ? (
                    <div style={{ marginTop: "0.2rem" }}>
                      <Badge
                        text={sceneObject.status}
                        tone={
                          sceneObject.status === "execution_failed" || sceneObject.status === "cancelled"
                            ? "danger"
                            : sceneObject.status === "validated" || sceneObject.status === "completed"
                              ? "ok"
                              : "warn"
                        }
                      />
                    </div>
                  ) : null}
                  {sceneObject.spatial_ref_id ? (
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.2rem" }}>
                      {sceneObject.spatial_ref_id}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

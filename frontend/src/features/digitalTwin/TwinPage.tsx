import { ChangeEvent, Suspense, lazy, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTwinSceneModel } from "@/features/digitalTwin/hooks";
import { CONGESTION_POLICY_VERSION } from "@/features/digitalTwin/sceneAdapter";
import type { TwinMetricSnapshot } from "@/features/digitalTwin/sceneAdapter";
import type { ImportSummary } from "@/features/digitalTwin/twinImport";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { useTopologyGraph, useTopologyNode } from "@/features/topology/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { usePrefersReducedMotion } from "@/shared/lib/reduced-motion";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { formatNumber, formatTimestamp } from "@/shared/lib/format";
import { useUpdateDeviceSpatialRef } from "@/features/networks/hooks";
import { useUiStore } from "@/shared/state/ui-store";

interface LayerState {
  showLinks: boolean;
  showLabels: boolean;
  showCongestion: boolean;
  showOverlays: boolean;
}

interface IntentHandoffPrefill {
  source: "digital-twin";
  action: string;
  scopeJson: string;
  constraintsJson: string;
  contextSummary: string;
}

const TwinScene = lazy(async () => {
  const module = await import("@/features/digitalTwin/TwinScene");
  return { default: module.TwinScene };
});

const DEFAULT_LAYERS: LayerState = {
  showLinks: true,
  showLabels: true,
  showCongestion: true,
  showOverlays: true,
};

function toSeverityTone(severity: "low" | "medium" | "high" | "neutral"): "ok" | "warn" | "danger" | "neutral" {
  if (severity === "low") {
    return "ok";
  }
  if (severity === "medium") {
    return "warn";
  }
  if (severity === "high") {
    return "danger";
  }
  return "neutral";
}

function MetricSnapshotList({ metrics }: { metrics: TwinMetricSnapshot[] }) {
  if (metrics.length === 0) {
    return <div style={{ color: "var(--ink-3)", fontSize: "0.84rem" }}>No congestion-relevant telemetry metrics found.</div>;
  }

  return (
    <div style={{ display: "grid", gap: "0.3rem" }}>
      {metrics.slice(0, 4).map((metric) => (
        <div
          key={`${metric.metric}:${metric.observedAt}`}
          style={{
            border: "1px solid var(--line-soft)",
            borderRadius: "8px",
            padding: "0.34rem 0.42rem",
            display: "grid",
            gap: "0.14rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem" }}>
            <strong>{metric.metric}</strong>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-2)" }}>
              {formatNumber(metric.value)} {metric.unit ?? ""}
            </span>
          </div>
          <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
            score {formatNumber(metric.normalizedScore * 100, 0)}% | {metric.policyId} {metric.severity} | {metric.source}
          </div>
          <div style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>{formatTimestamp(metric.observedAt)}</div>
        </div>
      ))}
    </div>
  );
}

function recommendIntentAction(severity: "low" | "medium" | "high" | "neutral") {
  if (severity === "high") {
    return "throttle_qos";
  }
  if (severity === "medium") {
    return "optimize_wireless_capacity";
  }
  return "reroute_path";
}

function buildIntentHandoffFromNode(
  node: {
    id: string;
    hostname: string;
    type: string;
    spatialRefId: string | null;
    congestion: {
      severity: "low" | "medium" | "high" | "neutral";
      score: number | null;
      policyVersion: string;
      primaryPolicyId: string | null;
      metrics: TwinMetricSnapshot[];
    };
  },
): IntentHandoffPrefill {
  const action = recommendIntentAction(node.congestion.severity);
  const topMetric = node.congestion.metrics[0] ?? null;
  const scope = {
    source: "digital_twin",
    device_id: node.id,
    spatial_ref_id: node.spatialRefId,
    congestion: {
      severity: node.congestion.severity,
      score: node.congestion.score,
      policy_id: node.congestion.primaryPolicyId,
      metric: topMetric
        ? {
            name: topMetric.metric,
            value: topMetric.value,
            unit: topMetric.unit,
            severity: topMetric.severity,
          }
        : null,
    },
  };

  const constraints = {
    max_downtime: 0,
    preserve_connectivity: true,
    simulation_required: true,
    context_source: "digital_twin",
  };

  const summary = [
    `device=${node.hostname}`,
    `severity=${node.congestion.severity}`,
    `policy=${node.congestion.primaryPolicyId ?? "none"}`,
  ].join(" | ");

  return {
    source: "digital-twin",
    action,
    scopeJson: JSON.stringify(scope),
    constraintsJson: JSON.stringify(constraints),
    contextSummary: summary,
  };
}

export function TwinPage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const pushToast = useUiStore((state) => state.pushToast);

  const graphQuery = useTopologyGraph(token, networkId);
  const baseGraph = graphQuery.data?.data;

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [layers, setLayers] = useState<LayerState>(DEFAULT_LAYERS);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [modelFileName, setModelFileName] = useState<string | null>(null);
  const [pendingPersistDeviceId, setPendingPersistDeviceId] = useState<string | null>(null);

  const prefersReducedMotion = usePrefersReducedMotion();
  const isNarrowViewport = useIsNarrowViewport();

  const topologyStatus = useLiveStore((state) => state.topologyStatus);
  const digitalTwinStatus = useLiveStore((state) => state.digitalTwinStatus);
  const updateSpatialRefMutation = useUpdateDeviceSpatialRef(token, networkId);

  const sceneModel = useTwinSceneModel(baseGraph?.nodes ?? [], baseGraph?.edges ?? [], importSummary?.mappingByDeviceId);

  const nodeQuery = useTopologyNode(token, selectedNodeId);

  const liveSceneCards = useMemo(() => {
    return sceneModel.overlays.slice(0, 8).map((overlay) => ({
      id: overlay.id,
      object_type: overlay.objectType,
      status: overlay.status,
      spatial_ref_id: overlay.spatialRefId,
    }));
  }, [sceneModel.overlays]);

  const inspectorNodes = useMemo(() => {
    return sceneModel.nodes
      .map((node) => ({ id: node.id, label: `${node.hostname} (${node.type})` }))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [sceneModel.nodes]);

  const selectedNode = selectedNodeId ? sceneModel.nodeById[selectedNodeId] : null;

  const selectedNodePersistedSpatialRef = useMemo(() => {
    if (!selectedNodeId) {
      return null;
    }
    const raw = baseGraph?.nodes.find((node) => node.device_id === selectedNodeId)?.spatial_ref_id;
    return typeof raw === "string" && raw.trim() ? raw.trim() : null;
  }, [baseGraph?.nodes, selectedNodeId]);

  const graphNodes = useMemo(() => {
    return (baseGraph?.nodes ?? []).map((node) => ({
      device_id: node.device_id,
      spatial_ref_id: node.spatial_ref_id,
    }));
  }, [baseGraph?.nodes]);

  const hasImportedSpatialRef = selectedNode
    ? Boolean(importSummary?.mappingByDeviceId[selectedNode.id])
    : false;
  const hasPersistedSpatialRef = Boolean(selectedNodePersistedSpatialRef);
  const canPersistSelectedNodeSpatialRef = Boolean(
    selectedNode &&
      hasImportedSpatialRef &&
      selectedNode.spatialRefId &&
      selectedNode.spatialRefId !== selectedNodePersistedSpatialRef &&
      token &&
      networkId,
  );

  async function persistSelectedNodeSpatialRef() {
    if (!selectedNode || !selectedNode.spatialRefId || !token || !networkId) {
      return;
    }

    setPendingPersistDeviceId(selectedNode.id);
    try {
      await updateSpatialRefMutation.mutateAsync({
        deviceId: selectedNode.id,
        spatialRefId: selectedNode.spatialRefId,
      });
      pushToast({
        tone: "ok",
        title: "Spatial mapping persisted",
        description: `${selectedNode.hostname} now uses spatial_ref_id ${selectedNode.spatialRefId}.`,
      });
    } catch (error) {
      const description = error instanceof Error ? error.message : "Could not persist spatial mapping.";
      pushToast({
        tone: "danger",
        title: "Spatial mapping persist failed",
        description,
      });
    } finally {
      setPendingPersistDeviceId(null);
    }
  }

  function handleConfigureIntentWorkflow() {
    if (!selectedNode) {
      navigate("/ops/intent");
      return;
    }

    const handoff = buildIntentHandoffFromNode(selectedNode);
    const query = new URLSearchParams();
    query.set("source", handoff.source);
    query.set("action", handoff.action);
    query.set("scope", handoff.scopeJson);
    query.set("constraints", handoff.constraintsJson);
    query.set("context_summary", handoff.contextSummary);
    navigate(`/ops/intent?${query.toString()}`);
  }

  async function onCampusImport(modelFile: File | null, mappingFile: File | null) {
    if (!modelFile) {
      setImportError("Select a GLB or GLTF file to import.");
      return;
    }

    const importModule = await import("@/features/digitalTwin/twinImport");

    const modelValidation = importModule.validateModelFile(modelFile);
    if (!modelValidation.ok) {
      setImportError(modelValidation.message);
      return;
    }

    if (mappingFile && !mappingFile.name.toLowerCase().endsWith(".json")) {
      setImportError("Sidecar mapping must be a JSON file.");
      return;
    }

    setIsImporting(true);
    setImportError(null);
    try {
      const summary = await importModule.parseImportSummary(modelFile, mappingFile, graphNodes);
      setImportSummary(summary);
      setModelFileName(modelFile.name);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Import validation failed.");
    } finally {
      setIsImporting(false);
    }
  }

  async function handleModelUpload(event: ChangeEvent<HTMLInputElement>) {
    const modelFile = event.target.files?.[0] ?? null;
    await onCampusImport(modelFile, null);
  }

  async function handleSidecarUpload(event: ChangeEvent<HTMLInputElement>) {
    const mappingFile = event.target.files?.[0] ?? null;
    if (!mappingFile) {
      return;
    }

    if (!modelFileName) {
      setImportError("Upload a GLB/GLTF model first, then upload sidecar mapping JSON.");
      return;
    }

    const syntheticModel = new File([""], modelFileName, { type: "model/gltf-binary" });
    await onCampusImport(syntheticModel, mappingFile);
  }

  function toggleLayer(layerKey: keyof LayerState) {
    setLayers((previous) => ({
      ...previous,
      [layerKey]: !previous[layerKey],
    }));
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel
        title="3D Digital Twin"
        subtitle="Primary operations surface with deterministic spatial layout and realtime overlays"
        action={
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Badge text={`topology ${topologyStatus}`} tone={topologyStatus === "open" ? "ok" : "warn"} />
            <Badge text={`digital twin ${digitalTwinStatus}`} tone={digitalTwinStatus === "open" ? "ok" : "warn"} />
          </div>
        }
      >
        <QueryState
          query={graphQuery}
          hasData={(data) => data.data.nodes.length > 0 || sceneModel.nodes.length > 0}
          emptyTitle="Topology graph is empty"
          emptyDescription="Add devices and wait for topology websocket deltas."
        >
          {() => (
            <div style={{ display: "grid", gap: "0.7rem" }}>
              <div
                role="group"
                aria-label="Digital twin layer controls"
                style={{
                  display: "grid",
                  gridTemplateColumns: isNarrowViewport ? "1fr 1fr" : "repeat(4, minmax(0, 1fr))",
                  gap: "0.5rem",
                }}
              >
                <Button
                  type="button"
                  tone={layers.showLinks ? "primary" : "ghost"}
                  aria-pressed={layers.showLinks}
                  onClick={() => toggleLayer("showLinks")}
                >
                  Links
                </Button>
                <Button
                  type="button"
                  tone={layers.showLabels ? "primary" : "ghost"}
                  aria-pressed={layers.showLabels}
                  onClick={() => toggleLayer("showLabels")}
                >
                  Labels
                </Button>
                <Button
                  type="button"
                  tone={layers.showCongestion ? "primary" : "ghost"}
                  aria-pressed={layers.showCongestion}
                  onClick={() => toggleLayer("showCongestion")}
                >
                  Congestion
                </Button>
                <Button
                  type="button"
                  tone={layers.showOverlays ? "primary" : "ghost"}
                  aria-pressed={layers.showOverlays}
                  onClick={() => toggleLayer("showOverlays")}
                >
                  Simulation/Intent
                </Button>
              </div>

              <div
                style={{
                  border: "1px solid var(--line-soft)",
                  borderRadius: "10px",
                  padding: "0.48rem 0.56rem",
                  display: "grid",
                  gap: "0.3rem",
                }}
              >
                <strong style={{ fontSize: "0.9rem" }}>Congestion legend</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={`policy ${CONGESTION_POLICY_VERSION}`} tone="info" />
                  <Badge text="priority loss>latency>util>cpu" tone="neutral" />
                  <Badge text="neutral unavailable metrics" tone="neutral" />
                </div>
                <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>
                  Uses existing telemetry metric+unit and optional `metric.tags.congestion_policy` hints.
                </div>
              </div>

              <div
                style={{
                  border: "1px solid var(--line-soft)",
                  borderRadius: "10px",
                  padding: "0.48rem 0.56rem",
                  display: "grid",
                  gap: "0.3rem",
                }}
              >
                <strong style={{ fontSize: "0.9rem" }}>Spatial mapping state</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text="persisted spatial_ref_id from topology" tone="ok" />
                  <Badge text="session mapping from import sidecar" tone="warn" />
                </div>
                <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>
                  Session mapping is local-only until persisted using existing device update API.
                </div>
              </div>

              <Suspense fallback={<div style={{ color: "var(--ink-3)" }}>Loading 3D scene...</div>}>
                <TwinScene
                  nodes={sceneModel.nodes}
                  links={sceneModel.links}
                  overlays={sceneModel.overlays}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  reducedMotion={prefersReducedMotion}
                  layers={layers}
                />
              </Suspense>
            </div>
          )}
        </QueryState>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Inspector" subtitle="Device identity, topology, spatial reference, and congestion snapshot">
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

          {selectedNode ? (
            <div style={{ display: "grid", gap: "0.42rem", marginBottom: "0.75rem" }}>
              <div style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.5rem" }}>
                <strong>{selectedNode.hostname}</strong>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  {selectedNode.id}
                </div>
                <div style={{ marginTop: "0.2rem", display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={selectedNode.type} tone="info" />
                  <Badge text={selectedNode.status} tone={selectedNode.status === "active" ? "ok" : "warn"} />
                  <Badge text={`congestion ${selectedNode.congestion.severity}`} tone={toSeverityTone(selectedNode.congestion.severity)} />
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.2rem" }}>
                  spatial_ref_id: {selectedNode.spatialRefId ?? "none"}
                </div>
                <div style={{ marginTop: "0.2rem", display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={hasPersistedSpatialRef ? "persisted" : "not persisted"} tone={hasPersistedSpatialRef ? "ok" : "warn"} />
                  {hasImportedSpatialRef ? <Badge text="session import" tone="warn" /> : null}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.12rem" }}>
                  congestion_score: {selectedNode.congestion.score === null ? "neutral" : `${formatNumber(selectedNode.congestion.score * 100, 0)}%`}
                </div>
                {selectedNode.congestion.primaryPolicyId ? (
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.12rem" }}>
                    congestion_policy: {selectedNode.congestion.primaryPolicyId} ({selectedNode.congestion.policyVersion})
                  </div>
                ) : null}
              </div>

              <MetricSnapshotList metrics={selectedNode.congestion.metrics} />

              {hasImportedSpatialRef ? (
                <Button
                  type="button"
                  tone="ghost"
                  disabled={!canPersistSelectedNodeSpatialRef || pendingPersistDeviceId === selectedNode.id}
                  onClick={persistSelectedNodeSpatialRef}
                >
                  {pendingPersistDeviceId === selectedNode.id ? "Persisting mapping..." : "Persist Mapping to Device"}
                </Button>
              ) : null}

              <Button type="button" tone="ghost" onClick={handleConfigureIntentWorkflow}>Configure in Intent Workflow</Button>
            </div>
          ) : null}

          <QueryState
            query={nodeQuery}
            emptyTitle="Select a node"
            emptyDescription="Click a 3D object to inspect topology neighbours."
          >
            {(nodeData) => (
              <div style={{ display: "grid", gap: "0.45rem" }}>
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

      <Panel title="Easy Campus Import (Session Only)" subtitle="Upload GLB/GLTF and optional sidecar mapping JSON. No backend persistence.">
        <div style={{ display: "grid", gap: "0.65rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "0.6rem" }}>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                Model file (.glb or .gltf)
              </span>
              <input aria-label="Campus model file" type="file" accept=".glb,.gltf,model/gltf-binary,model/gltf+json" onChange={handleModelUpload} />
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                Sidecar mapping (.json, optional)
              </span>
              <input aria-label="Campus mapping file" type="file" accept=".json,application/json" onChange={handleSidecarUpload} />
            </label>
          </div>

          {isImporting ? <div style={{ color: "var(--ink-3)" }}>Validating campus import files...</div> : null}
          {importError ? <div role="status" style={{ color: "var(--danger)", fontSize: "0.88rem" }}>{importError}</div> : null}

          {importSummary ? (
            <div
              style={{
                border: "1px solid var(--line-soft)",
                borderRadius: "10px",
                padding: "0.5rem 0.56rem",
                display: "grid",
                gap: "0.36rem",
              }}
            >
              <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                <Badge text={`model ${importSummary.modelType.toUpperCase()}`} tone="info" />
                <Badge text={`rows ${importSummary.totalRows}`} tone="neutral" />
                <Badge text={`matched ${importSummary.matched}`} tone="ok" />
                <Badge text={`unmatched ${importSummary.unmatched}`} tone={importSummary.unmatched > 0 ? "warn" : "ok"} />
                <Badge
                  text={`duplicates ${importSummary.duplicateKeys.length}`}
                  tone={importSummary.duplicateKeys.length > 0 ? "danger" : "ok"}
                />
              </div>
              <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                model: {importSummary.modelFileName}
              </div>
              <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                mapping: {importSummary.mappingFileName ?? "none"}
              </div>
              {importSummary.duplicateKeys.length > 0 ? (
                <div className="mono" style={{ color: "var(--danger)", fontSize: "0.74rem" }}>
                  duplicate object_name entries: {importSummary.duplicateKeys.slice(0, 6).join(", ")}
                </div>
              ) : null}
              <div style={{ color: "var(--ink-3)", fontSize: "0.82rem" }}>
                Imported mapping is kept in local session state only and is cleared on page reload.
              </div>

              <div style={{ color: "var(--ink-3)", fontSize: "0.82rem" }}>
                Use "Persist Mapping to Device" in Inspector to save an imported mapping with the existing device update API.
              </div>
            </div>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

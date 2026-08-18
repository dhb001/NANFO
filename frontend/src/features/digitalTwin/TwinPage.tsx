import { ChangeEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TwinScene } from "@/features/digitalTwin/TwinScene";
import { useTwinSceneModel } from "@/features/digitalTwin/hooks";
import { CONGESTION_THRESHOLDS } from "@/features/digitalTwin/sceneAdapter";
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

interface LayerState {
  showLinks: boolean;
  showLabels: boolean;
  showCongestion: boolean;
  showOverlays: boolean;
}

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
            score {formatNumber(metric.normalizedScore * 100, 0)}% | {metric.source}
          </div>
          <div style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>{formatTimestamp(metric.observedAt)}</div>
        </div>
      ))}
    </div>
  );
}

export function TwinPage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);

  const graphQuery = useTopologyGraph(token, networkId);
  const baseGraph = graphQuery.data?.data;

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [layers, setLayers] = useState<LayerState>(DEFAULT_LAYERS);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [modelFileName, setModelFileName] = useState<string | null>(null);

  const prefersReducedMotion = usePrefersReducedMotion();
  const isNarrowViewport = useIsNarrowViewport();

  const topologyStatus = useLiveStore((state) => state.topologyStatus);
  const digitalTwinStatus = useLiveStore((state) => state.digitalTwinStatus);

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

  const graphNodes = useMemo(() => {
    return (baseGraph?.nodes ?? []).map((node) => ({
      device_id: node.device_id,
      spatial_ref_id: node.spatial_ref_id,
    }));
  }, [baseGraph?.nodes]);

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
                  <Badge text={`low < ${formatNumber(CONGESTION_THRESHOLDS.lowUpperExclusive * 100, 0)}%`} tone="ok" />
                  <Badge
                    text={`medium ${formatNumber(CONGESTION_THRESHOLDS.lowUpperExclusive * 100, 0)}-${formatNumber(
                      CONGESTION_THRESHOLDS.mediumUpperExclusive * 100,
                      0,
                    )}%`}
                    tone="warn"
                  />
                  <Badge text={`high >= ${formatNumber(CONGESTION_THRESHOLDS.mediumUpperExclusive * 100, 0)}%`} tone="danger" />
                  <Badge text="neutral unavailable metrics" tone="neutral" />
                </div>
                <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>
                  Based on existing telemetry only (recognized percent utilization/loss/cpu/bandwidth or latency ms metrics).
                </div>
              </div>

              <TwinScene
                nodes={sceneModel.nodes}
                links={sceneModel.links}
                overlays={sceneModel.overlays}
                selectedNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
                reducedMotion={prefersReducedMotion}
                layers={layers}
              />
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
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.12rem" }}>
                  congestion_score: {selectedNode.congestion.score === null ? "neutral" : `${formatNumber(selectedNode.congestion.score * 100, 0)}%`}
                </div>
              </div>

              <MetricSnapshotList metrics={selectedNode.congestion.metrics} />

              <Button type="button" tone="ghost" onClick={() => navigate("/ops/intent")}>Configure in Intent Workflow</Button>
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
            </div>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

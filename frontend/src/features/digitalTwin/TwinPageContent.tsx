import { ChangeEvent, Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CampusFocusControls } from "@/features/digitalTwin/CampusFocusControls";
import { DeviceLegendPanel } from "@/features/digitalTwin/DeviceLegendPanel";
import { MetricSnapshotList } from "@/features/digitalTwin/MetricSnapshotList";
import {
  deriveSpatialBuildingScope,
  type CampusBuildingViewState,
} from "@/features/digitalTwin/campusBuildings";
import {
  mapImportedBuildingsToCampusBuildings,
  mapPersistedCampusBuildingRecordsToCampusBuildings,
  parseCampusGeoJson,
  type ImportedCampusBuilding,
  type CampusImportParseResult,
} from "@/features/digitalTwin/campusImportProvider";
import { useTwinSceneModel } from "@/features/digitalTwin/hooks";
import { CONGESTION_POLICY_VERSION } from "@/features/digitalTwin/sceneAdapter";
import type { ImportSummary } from "@/features/digitalTwin/twinImport";
import { WIRELESS_COVERAGE_POLICY_VERSION } from "@/features/digitalTwin/wirelessCoverage";
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
import { formatNumber } from "@/shared/lib/format";
import {
  useCampusModelAssets,
  useCampusBuildings,
  useDeviceGroups,
  useUpdateDeviceSpatialRef,
  useUpsertCampusModelAssets,
  useUpsertCampusBuildings,
  useUpsertDeviceGroups,
} from "@/features/networks/hooks";
import { useUiStore } from "@/shared/state/ui-store";

interface LayerState {
  showLinks: boolean;
  showLabels: boolean;
  showCongestion: boolean;
  showOverlays: boolean;
  showModel: boolean;
  showWirelessCoverage: boolean;
  showImportedBuildings: boolean;
}

type ImportedModelStatus = "idle" | "loading" | "ready" | "error";

const TwinScene = lazy(async () => {
  const module = await import("@/features/digitalTwin/TwinScene");
  return { default: module.TwinScene };
});

const DEFAULT_LAYERS: LayerState = {
  showLinks: true,
  showLabels: true,
  showCongestion: true,
  showOverlays: true,
  showModel: true,
  showWirelessCoverage: true,
  showImportedBuildings: true,
};

function createSessionModelUrl(modelFile: File): string {
  if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
    return URL.createObjectURL(modelFile);
  }
  return `session-model://${encodeURIComponent(modelFile.name)}`;
}

function revokeSessionModelUrl(modelUrl: string | null): void {
  if (!modelUrl || !modelUrl.startsWith("blob:")) {
    return;
  }

  if (typeof URL === "undefined" || typeof URL.revokeObjectURL !== "function") {
    return;
  }

  URL.revokeObjectURL(modelUrl);
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  const bytes = new Uint8Array(digest);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

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

function isWirelessDeviceType(deviceType: string): boolean {
  const normalized = deviceType.trim().toLowerCase();
  return normalized.includes("wireless") || normalized === "ap" || normalized.endsWith("_ap");
}

function pickMostCommonValue(values: Array<string | null>): string | null {
  const counts = new Map<string, number>();
  for (const value of values) {
    if (!value) {
      continue;
    }
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }

  let selected: string | null = null;
  let selectedCount = -1;
  for (const [value, count] of counts.entries()) {
    if (count > selectedCount || (count === selectedCount && (selected === null || value.localeCompare(selected) < 0))) {
      selected = value;
      selectedCount = count;
    }
  }

  return selected;
}

function toSafeGroupToken(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9:_-]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized || "scope";
}

export function TwinPageContent() {
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
  const [importedModelUrl, setImportedModelUrl] = useState<string | null>(null);
  const [importedModelStatus, setImportedModelStatus] = useState<ImportedModelStatus>("idle");
  const [importedModelStatusMessage, setImportedModelStatusMessage] = useState<string | null>(null);
  const [pendingPersistDeviceId, setPendingPersistDeviceId] = useState<string | null>(null);
  const [importedCampusBuildings, setImportedCampusBuildings] = useState<ImportedCampusBuilding[]>([]);
  const [campusImportSummary, setCampusImportSummary] = useState<CampusImportParseResult["summary"] | null>(null);
  const [campusImportError, setCampusImportError] = useState<string | null>(null);
  const [isCampusImporting, setIsCampusImporting] = useState(false);
  const [isPersistingCampus, setIsPersistingCampus] = useState(false);
  const [isPersistingModelAsset, setIsPersistingModelAsset] = useState(false);
  const [isPersistingDeviceGroups, setIsPersistingDeviceGroups] = useState(false);
  const [selectedBuildingId, setSelectedBuildingId] = useState<string | null>(null);
  const [selectedFloorKey, setSelectedFloorKey] = useState<string | null>(null);
  const [focusSelectedBuildingOnly, setFocusSelectedBuildingOnly] = useState(false);
  const [filterSelectedFloorOnly, setFilterSelectedFloorOnly] = useState(false);
  const [currentModelFile, setCurrentModelFile] = useState<File | null>(null);

  useEffect(() => {
    return () => {
      revokeSessionModelUrl(importedModelUrl);
    };
  }, [importedModelUrl]);

  const prefersReducedMotion = usePrefersReducedMotion();
  const isNarrowViewport = useIsNarrowViewport();

  const topologyStatus = useLiveStore((state) => state.topologyStatus);
  const digitalTwinStatus = useLiveStore((state) => state.digitalTwinStatus);
  const liveAlerts = useLiveStore((state) => state.alerts);
  const updateSpatialRefMutation = useUpdateDeviceSpatialRef(token, networkId);
  const campusBuildingsQuery = useCampusBuildings(token, networkId);
  const campusModelAssetsQuery = useCampusModelAssets(token, networkId);
  const deviceGroupsQuery = useDeviceGroups(token, networkId);
  const upsertCampusBuildingsMutation = useUpsertCampusBuildings(token, networkId);
  const upsertCampusModelAssetsMutation = useUpsertCampusModelAssets(token, networkId);
  const upsertDeviceGroupsMutation = useUpsertDeviceGroups(token, networkId);

  const sceneModel = useTwinSceneModel(baseGraph?.nodes ?? [], baseGraph?.edges ?? [], importSummary?.mappingByDeviceId);

  const persistedCampusBuildings = useMemo(() => {
    return mapPersistedCampusBuildingRecordsToCampusBuildings(campusBuildingsQuery.data?.items ?? []);
  }, [campusBuildingsQuery.data?.items]);

  const effectiveCampusBuildings = useMemo(() => {
    if (layers.showImportedBuildings && importedCampusBuildings.length > 0) {
      return mapImportedBuildingsToCampusBuildings(importedCampusBuildings);
    }
    if (persistedCampusBuildings.length > 0) {
      return persistedCampusBuildings;
    }
    return undefined;
  }, [importedCampusBuildings, layers.showImportedBuildings, persistedCampusBuildings]);

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

  const selectedNodeScope = useMemo(() => {
    return deriveSpatialBuildingScope(selectedNode?.spatialRefId);
  }, [selectedNode?.spatialRefId]);

  const resolvedBuildingId = selectedBuildingId ?? selectedNodeScope.buildingId;
  const resolvedFloorKey = selectedFloorKey ?? selectedNodeScope.floorKey;

  const buildingViewState = useMemo<CampusBuildingViewState | undefined>(() => {
    if (!resolvedBuildingId && !resolvedFloorKey && !focusSelectedBuildingOnly && !filterSelectedFloorOnly) {
      return undefined;
    }

    return {
      selectedBuildingId: resolvedBuildingId,
      selectedFloorKey: resolvedFloorKey,
      floorFilterEnabled: filterSelectedFloorOnly,
      visibleBuildingIds:
        focusSelectedBuildingOnly && resolvedBuildingId
          ? new Set([resolvedBuildingId])
          : undefined,
    };
  }, [
    filterSelectedFloorOnly,
    focusSelectedBuildingOnly,
    resolvedBuildingId,
    resolvedFloorKey,
  ]);

  const selectedNodePersistedSpatialRef = useMemo(() => {
    if (!selectedNodeId) {
      return null;
    }
    const raw = baseGraph?.nodes.find((node) => node.device_id === selectedNodeId)?.spatial_ref_id;
    return typeof raw === "string" && raw.trim() ? raw.trim() : null;
  }, [baseGraph?.nodes, selectedNodeId]);

  const latestPersistedModelAsset = useMemo(() => {
    const items = campusModelAssetsQuery.data?.items ?? [];
    return items.length > 0 ? items[items.length - 1] : null;
  }, [campusModelAssetsQuery.data?.items]);

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

  const persistSelectedNodeSpatialRef = useCallback(async () => {
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
  }, [networkId, pushToast, selectedNode, token, updateSpatialRefMutation]);

  const parseCampusGeoJsonFile = useCallback(async (file: File | null) => {
    if (!file) {
      return;
    }

    const lowerName = file.name.toLowerCase();
    const mime = file.type.toLowerCase();
    const isJsonLike =
      lowerName.endsWith(".json") ||
      lowerName.endsWith(".geojson") ||
      mime.includes("application/json") ||
      mime.includes("application/geo+json");

    if (!isJsonLike) {
      setCampusImportError("Campus file must be .geojson or .json.");
      return;
    }

    setIsCampusImporting(true);
    setCampusImportError(null);
    try {
      const text = await file.text();
      const parsed = parseCampusGeoJson(text);
      setImportedCampusBuildings(parsed.buildings);
      setCampusImportSummary(parsed.summary);
    } catch (error) {
      setCampusImportError(error instanceof Error ? error.message : "Could not parse campus GeoJSON.");
      setImportedCampusBuildings([]);
      setCampusImportSummary(null);
    } finally {
      setIsCampusImporting(false);
    }
  }, []);

  const persistImportedCampusBuildings = useCallback(async () => {
    if (!networkId || !token || importedCampusBuildings.length === 0) {
      return;
    }

    setIsPersistingCampus(true);
    try {
      await upsertCampusBuildingsMutation.mutateAsync({
        replaceExisting: true,
        buildings: importedCampusBuildings.map((building) => ({
          building_id: building.id,
          campus_key: building.campusKey,
          building_key: building.buildingKey,
          label: building.label,
          geometry: building.geometry,
          x: building.x,
          z: building.z,
          base_y: building.baseY,
          width: building.width,
          depth: building.depth,
          height: building.height,
          floors: building.floors,
          footprint: building.footprint,
          wall_material: building.wallMaterial,
          attenuation_db: building.attenuationDb,
          source: building.source,
        })),
      });
      pushToast({
        tone: "ok",
        title: "Campus buildings persisted",
        description: `${importedCampusBuildings.length} building records saved for this network.`,
      });
    } catch (error) {
      pushToast({
        tone: "danger",
        title: "Campus building persist failed",
        description: error instanceof Error ? error.message : "Could not save campus buildings.",
      });
    } finally {
      setIsPersistingCampus(false);
    }
  }, [importedCampusBuildings, networkId, pushToast, token, upsertCampusBuildingsMutation]);

  const persistImportedModelAsset = useCallback(async () => {
    if (!networkId || !token || !currentModelFile || !importSummary) {
      return;
    }

    if (typeof crypto === "undefined" || !crypto.subtle) {
      pushToast({
        tone: "danger",
        title: "Model asset persist failed",
        description: "This browser context does not support Web Crypto SHA-256.",
      });
      return;
    }

    setIsPersistingModelAsset(true);
    try {
      const modelBuffer = await currentModelFile.arrayBuffer();
      const modelDataBase64 = toBase64(modelBuffer);
      const modelSha256 = await sha256Hex(modelBuffer);

      await upsertCampusModelAssetsMutation.mutateAsync({
        model_file_name: currentModelFile.name,
        model_mime_type: currentModelFile.type || "application/octet-stream",
        model_data_base64: modelDataBase64,
        model_sha256: modelSha256,
        model_size_bytes: modelBuffer.byteLength,
        mapping_by_device_id: importSummary.mappingByDeviceId,
        source: "session_import",
        replace_existing: true,
      });

      pushToast({
        tone: "ok",
        title: "Campus model asset persisted",
        description: `${currentModelFile.name} saved for this network.`,
      });
    } catch (error) {
      pushToast({
        tone: "danger",
        title: "Model asset persist failed",
        description: error instanceof Error ? error.message : "Could not persist model asset.",
      });
    } finally {
      setIsPersistingModelAsset(false);
    }
  }, [
    currentModelFile,
    importSummary,
    networkId,
    pushToast,
    token,
    upsertCampusModelAssetsMutation,
  ]);

  const persistDerivedDeviceGroups = useCallback(async () => {
    if (!networkId || !token || sceneModel.nodes.length === 0) {
      return;
    }

    setIsPersistingDeviceGroups(true);
    try {
      const nodesWithScope = sceneModel.nodes.map((node) => ({
        node,
        scope: deriveSpatialBuildingScope(node.spatialRefId),
      }));

      const scopedBuildingId = resolvedBuildingId ?? pickMostCommonValue(nodesWithScope.map(({ scope }) => scope.buildingId));
      const scopedFloorKey =
        resolvedFloorKey ??
        pickMostCommonValue(
          nodesWithScope
            .filter(({ scope }) => !scopedBuildingId || scope.buildingId === scopedBuildingId)
            .map(({ scope }) => scope.floorKey),
        );

      const scopedNodes = nodesWithScope
        .filter(({ scope }) => {
          if (scopedBuildingId && scope.buildingId !== scopedBuildingId) {
            return false;
          }
          if (scopedFloorKey && scope.floorKey !== scopedFloorKey) {
            return false;
          }
          return true;
        })
        .map(({ node }) => node);

      const effectiveNodes = scopedNodes.length > 0 ? scopedNodes : sceneModel.nodes;
      const wirelessDeviceIds = effectiveNodes
        .filter((node) => isWirelessDeviceType(node.type))
        .map((node) => node.id);
      const scopedDeviceIds = effectiveNodes.map((node) => node.id);

      const [scopeCampusKey, scopeBuildingKey] = scopedBuildingId?.split(":") ?? [];
      const sitePrefix =
        scopeCampusKey && scopeBuildingKey
          ? scopedFloorKey
            ? `${scopeCampusKey}/${scopeBuildingKey}/${scopedFloorKey}`
            : `${scopeCampusKey}/${scopeBuildingKey}`
          : null;

      const scopeToken = toSafeGroupToken(sitePrefix ?? "network");
      const scopeLabel = [scopeBuildingKey?.toUpperCase() ?? null, scopedFloorKey?.toUpperCase() ?? null]
        .filter((part): part is string => Boolean(part))
        .join(" ");

      const wirelessSelector: Record<string, string> = {
        functional_group: "wireless",
      };
      if (sitePrefix) {
        wirelessSelector.site_prefix = sitePrefix;
      }

      const operationsSelector: Record<string, string> = {};
      if (sitePrefix) {
        operationsSelector.site_prefix = sitePrefix;
      }

      await upsertDeviceGroupsMutation.mutateAsync({
        replaceExisting: true,
        groups: [
          {
            group_key: `wireless-${scopeToken}`.slice(0, 160),
            name: scopeLabel ? `${scopeLabel} Wireless` : "Wireless Devices",
            group_type: "functional",
            selector: wirelessSelector,
            device_ids: wirelessDeviceIds,
          },
          {
            group_key: `ops-${scopeToken}`.slice(0, 160),
            name: scopeLabel ? `${scopeLabel} Operations` : "Operations Devices",
            group_type: "operational",
            selector: operationsSelector,
            device_ids: scopedDeviceIds,
          },
        ],
      });

      pushToast({
        tone: "ok",
        title: "Device groups persisted",
        description: "Native network device groups updated for this campus context.",
      });
    } catch (error) {
      pushToast({
        tone: "danger",
        title: "Device group persist failed",
        description: error instanceof Error ? error.message : "Could not persist device groups.",
      });
    } finally {
      setIsPersistingDeviceGroups(false);
    }
  }, [
    networkId,
    pushToast,
    resolvedBuildingId,
    resolvedFloorKey,
    sceneModel.nodes,
    token,
    upsertDeviceGroupsMutation,
  ]);

  const handleConfigureIntentWorkflow = useCallback(async () => {
    if (!selectedNode) {
      navigate("/ops/intent");
      return;
    }

    const { buildIntentHandoffFromNode } = await import("@/features/digitalTwin/intentHandoff");
    const handoff = buildIntentHandoffFromNode(selectedNode);
    const query = new URLSearchParams();
    query.set("source", handoff.source);
    query.set("action", handoff.action);
    query.set("scope", handoff.scopeJson);
    query.set("constraints", handoff.constraintsJson);
    query.set("context_summary", handoff.contextSummary);
    navigate(`/ops/intent?${query.toString()}`);
  }, [navigate, selectedNode]);

  const onCampusImport = useCallback(async (
    modelFile: File | null,
    mappingFile: File | null,
    options: {
      replaceModelAsset: boolean;
    },
  ) => {
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

    if (options.replaceModelAsset) {
      const modelUrl = createSessionModelUrl(modelFile);
      revokeSessionModelUrl(importedModelUrl);
      setImportedModelUrl(modelUrl);
      setImportedModelStatus("loading");
      setImportedModelStatusMessage(null);
    }

    setIsImporting(true);
    setImportError(null);
    try {
      const summary = await importModule.parseImportSummary(modelFile, mappingFile, graphNodes);
      setImportSummary(summary);
      setModelFileName(modelFile.name);
      if (options.replaceModelAsset) {
        setCurrentModelFile(modelFile);
      }
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Import validation failed.");
    } finally {
      setIsImporting(false);
    }
  }, [graphNodes, importedModelUrl]);

  const handleModelUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const modelFile = event.target.files?.[0] ?? null;
    await onCampusImport(modelFile, null, { replaceModelAsset: true });
  }, [onCampusImport]);

  const handleSidecarUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const mappingFile = event.target.files?.[0] ?? null;
    if (!mappingFile) {
      return;
    }

    if (!modelFileName) {
      setImportError("Upload a GLB/GLTF model first, then upload sidecar mapping JSON.");
      return;
    }

    const syntheticModel = new File([""], modelFileName, { type: "model/gltf-binary" });
    await onCampusImport(syntheticModel, mappingFile, { replaceModelAsset: false });
  }, [modelFileName, onCampusImport]);

  const handleImportedModelStatusChange = useCallback((status: Exclude<ImportedModelStatus, "idle">, message?: string) => {
    setImportedModelStatus(status);
    if (status === "error") {
      setImportedModelStatusMessage(message ?? "Could not render the uploaded model.");
      return;
    }

    setImportedModelStatusMessage(null);
  }, []);

  function toggleLayer(layerKey: keyof LayerState) {
    setLayers((previous) => ({
      ...previous,
      [layerKey]: !previous[layerKey],
    }));
  }

  function handleSelectedBuildingChange(buildingId: string | null) {
    setSelectedBuildingId(buildingId);
    setSelectedFloorKey(null);
    setFilterSelectedFloorOnly(false);
  }

  function resetCampusFocus() {
    setSelectedBuildingId(null);
    setSelectedFloorKey(null);
    setFocusSelectedBuildingOnly(false);
    setFilterSelectedFloorOnly(false);
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel
        title="3D Digital Twin"
        subtitle="Spatial layout with live overlays"
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
                  gridTemplateColumns: isNarrowViewport ? "1fr 1fr" : "repeat(6, minmax(0, 1fr))",
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
                <Button
                  type="button"
                  tone={layers.showWirelessCoverage ? "primary" : "ghost"}
                  aria-pressed={layers.showWirelessCoverage}
                  onClick={() => toggleLayer("showWirelessCoverage")}
                >
                  Wireless coverage
                </Button>
                <Button
                  type="button"
                  tone={importedModelUrl && layers.showModel ? "primary" : "ghost"}
                  aria-pressed={Boolean(importedModelUrl) && layers.showModel}
                  disabled={!importedModelUrl}
                  onClick={() => toggleLayer("showModel")}
                >
                  Campus model
                </Button>
                <Button
                  type="button"
                  tone={layers.showImportedBuildings ? "primary" : "ghost"}
                  aria-pressed={layers.showImportedBuildings}
                  onClick={() => toggleLayer("showImportedBuildings")}
                >
                  OSM buildings
                </Button>
              </div>

              <CampusFocusControls
                nodes={sceneModel.nodes}
                selectedBuildingId={selectedBuildingId}
                resolvedBuildingId={resolvedBuildingId}
                selectedFloorKey={selectedFloorKey}
                resolvedFloorKey={resolvedFloorKey}
                focusSelectedBuildingOnly={focusSelectedBuildingOnly}
                filterSelectedFloorOnly={filterSelectedFloorOnly}
                onSelectedBuildingChange={handleSelectedBuildingChange}
                onSelectedFloorKeyChange={setSelectedFloorKey}
                onFocusSelectedBuildingOnlyChange={setFocusSelectedBuildingOnly}
                onFilterSelectedFloorOnlyChange={setFilterSelectedFloorOnly}
                onReset={resetCampusFocus}
              />

              <DeviceLegendPanel nodes={sceneModel.nodes} />

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
                  <Badge text="persisted spatial_ref_id" tone="ok" />
                  <Badge text="session sidecar mapping" tone="warn" />
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
                <strong style={{ fontSize: "0.9rem" }}>Imported model state</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge
                    text={`model ${importedModelStatus}`}
                    tone={
                      importedModelStatus === "ready"
                        ? "ok"
                        : importedModelStatus === "error"
                          ? "danger"
                          : importedModelStatus === "loading"
                            ? "warn"
                            : "neutral"
                    }
                  />
                  <Badge text={layers.showModel ? "layer visible" : "layer hidden"} tone={layers.showModel ? "ok" : "neutral"} />
                  <Badge
                    text={`persisted assets ${campusModelAssetsQuery.data?.total ?? 0}`}
                    tone={(campusModelAssetsQuery.data?.total ?? 0) > 0 ? "ok" : "neutral"}
                  />
                </div>
                {latestPersistedModelAsset ? (
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                    latest: {latestPersistedModelAsset.model_file_name} ({latestPersistedModelAsset.model_size_bytes} bytes)
                  </div>
                ) : null}
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    tone="ghost"
                    disabled={!currentModelFile || !importSummary || isPersistingModelAsset || !networkId || !token}
                    permission="write:config"
                    onClick={persistImportedModelAsset}
                  >
                    {isPersistingModelAsset ? "Persisting model asset..." : "Persist Model Asset"}
                  </Button>
                </div>
                {importedModelStatusMessage ? (
                  <div role="status" style={{ color: "var(--danger)", fontSize: "0.78rem" }}>
                    {importedModelStatusMessage}
                  </div>
                ) : null}
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
                <strong style={{ fontSize: "0.9rem" }}>Wireless coverage layer</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={`policy ${WIRELESS_COVERAGE_POLICY_VERSION}`} tone="info" />
                  <Badge text="synthetic estimate" tone="warn" />
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
                <strong style={{ fontSize: "0.9rem" }}>Campus buildings</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={campusImportSummary ? `features ${campusImportSummary.featureCount}` : "features 0"} tone="neutral" />
                  <Badge text={campusImportSummary ? `buildings ${campusImportSummary.buildingCount}` : "buildings 0"} tone="info" />
                  <Badge text={`persisted ${persistedCampusBuildings.length}`} tone={persistedCampusBuildings.length > 0 ? "ok" : "neutral"} />
                </div>
                <label style={{ display: "grid", gap: "0.3rem" }}>
                  <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                    Campus GeoJSON file
                  </span>
                  <input aria-label="Campus GeoJSON file" type="file" accept=".geojson,.json,application/geo+json,application/json" onChange={(event) => {
                    void parseCampusGeoJsonFile(event.target.files?.[0] ?? null);
                  }} />
                </label>
                {isCampusImporting ? <div style={{ color: "var(--ink-3)" }}>Parsing GeoJSON campus buildings...</div> : null}
                {campusImportError ? <div role="status" style={{ color: "var(--danger)", fontSize: "0.78rem" }}>{campusImportError}</div> : null}
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    tone="ghost"
                    disabled={importedCampusBuildings.length === 0 || isPersistingCampus || !networkId || !token}
                    permission="write:config"
                    onClick={persistImportedCampusBuildings}
                  >
                    {isPersistingCampus ? "Persisting buildings..." : "Persist Buildings to Network"}
                  </Button>
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
                <strong style={{ fontSize: "0.9rem" }}>Device groups</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={`persisted ${deviceGroupsQuery.data?.total ?? 0}`} tone={(deviceGroupsQuery.data?.total ?? 0) > 0 ? "ok" : "neutral"} />
                  <Badge text="native network groups" tone="info" />
                </div>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    tone="ghost"
                    disabled={sceneModel.nodes.length === 0 || isPersistingDeviceGroups || !networkId || !token}
                    permission="write:config"
                    onClick={persistDerivedDeviceGroups}
                  >
                    {isPersistingDeviceGroups ? "Persisting groups..." : "Persist Device Groups"}
                  </Button>
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
                  alerts={liveAlerts}
                  importedModelUrl={importedModelUrl}
                  importedCampusBuildings={effectiveCampusBuildings}
                  onImportedModelStatusChange={handleImportedModelStatusChange}
                  buildingViewState={buildingViewState}
                  onSelectBuilding={handleSelectedBuildingChange}
                />
              </Suspense>
            </div>
          )}
        </QueryState>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Inspector" subtitle="Device identity, topology, spatial reference, and congestion">
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
                  permission="write:config"
                  onClick={persistSelectedNodeSpatialRef}
                >
                  {pendingPersistDeviceId === selectedNode.id ? "Persisting mapping..." : "Persist Mapping to Device"}
                </Button>
              ) : null}

              <Button permission="write:config" type="button" tone="ghost" onClick={handleConfigureIntentWorkflow}>Configure in Intent Workflow</Button>
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

        <Panel title="Live Scene Deltas" subtitle="simulation and intent websocket deltas">
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

      <Panel title="Easy Campus Import (Session Only)" subtitle="Upload GLB/GLTF with optional sidecar mapping JSON.">
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
                Imported mapping is session-only and clears on reload.
              </div>

            </div>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

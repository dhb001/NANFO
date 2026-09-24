import { ChangeEvent, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  parseCampusGeoJsonFile,
  type ImportedCampusBuilding,
  type CampusImportParseResult,
} from "@/features/digitalTwin/campusImportProvider";
import { useTwinSceneModel } from "@/features/digitalTwin/hooks";
import {
  BACKEND_DETECTOR_RULES,
  HEURISTIC_LEVEL_TEXT,
  VISUAL_HEURISTIC_LABEL,
  activeAlertDeviceIds,
  deriveDeviceAlertStates,
  describeDetectorRule,
  describeDeviceAlerts,
} from "@/features/digitalTwin/twinSeverity";
import { useAlertsQuery } from "@/features/reliability/hooks";
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
import { SceneReconciliationStatus } from "@/features/realtime/SceneReconciliationStatus";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { formatTimestamp } from "@/shared/lib/format";
import {
  useCampusModelAssets,
  useCampusBuildings,
  useDeviceGroups,
  useUpdateDeviceSpatialRef,
  useUpsertCampusModelAssets,
  useUpsertCampusBuildings,
} from "@/features/networks/hooks";
import { useUiStore } from "@/shared/state/ui-store";
import type { MeasuredPathSegment } from "./measuredPathMapping";
import { hasPermission } from "@/features/auth/permissions";
import { useSessionScope } from "@/features/auth/sessionScope";
import { useSpatialScene } from "./spatialHooks";
import { applySpatialScene } from "./spatialScene";
import { SpatialScenePanel } from "./SpatialScenePanel";
import { ModelRegistrationControls } from "./ModelRegistration";
import type { AssetRegistration, CampusModelAssetRecord } from "@/shared/types/network";
import { registrationTransform, validateRegistration } from "./modelRegistration";
import { RFImportPanel, type RFImportState } from "./RFImportPanel";
import { TwinScene } from "./TwinScene";
import { decodePersistedModel, encodeBase64, loadValidatedModel, sha256Hex } from "./modelAsset";
import { buildIntentHandoffFromNode, intentHandoffQuery } from "./intentHandoff";
import * as importModule from "./twinImport";
import { downloadModelBytes } from "./assetDownload";
import { CustomGroupEditor } from "./CustomGroupEditor";
import { TwinLifecycleControls } from "./TwinLifecycleControls";
import { overlayTone } from "./twinStatusTones";
import { DeviceGroupsPanel } from "./DeviceGroupsPanel";
import type { GroupFocus } from "./groupProposal";

const MeasuredPathPanel = lazy(() => import("./MeasuredPathPanel").then((module) => ({ default: module.MeasuredPathPanel })));

interface LayerState {
  showLinks: boolean;
  showLabels: boolean;
  showCongestion: boolean;
  showOverlays: boolean;
  showModel: boolean;
  showImportedBuildings: boolean;
}

type ImportedModelStatus = "idle" | "loading" | "ready" | "error";

const DEFAULT_LAYERS: LayerState = {
  showLinks: true,
  showLabels: true,
  showCongestion: true,
  showOverlays: true,
  showModel: true,
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

const DETECTOR_RULE_TEXT = Object.entries(BACKEND_DETECTOR_RULES).map(([metric, rule]) => describeDetectorRule(metric, rule));

export function TwinPageContent() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.accessToken);
  const profile = useAuthStore((state) => state.profile);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const [rfImport, setRFImport] = useState<RFImportState | null>(null);
  const [showRFImport, setShowRFImport] = useState(false);
  const [showCustomGroups, setShowCustomGroups] = useState(false);
  const [openedCustomGroups, setOpenedCustomGroups] = useState(false);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [assetPage, setAssetPage] = useState(1);
  const [retainedAsset, setRetainedAsset] = useState<{ asset: CampusModelAssetRecord; page: number } | null>(null);
  const assetScope = useSessionScope();
  const pushToast = useUiStore((state) => state.pushToast);

  const graphQuery = useTopologyGraph(token, networkId);
  const baseGraph = graphQuery.data?.data;

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [measuredPath, setMeasuredPath] = useState<MeasuredPathSegment[] | null>(null);
  const [showMeasuredPaths, setShowMeasuredPaths] = useState(false);
  const [layers, setLayers] = useState<LayerState>(DEFAULT_LAYERS);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [modelFileName, setModelFileName] = useState<string | null>(null);
  const [importedModelUrl, setImportedModelUrl] = useState<string | null>(null);
  const [registration, setRegistration] = useState<{ url: string; value: AssetRegistration; saved: boolean } | null>(null);
  const [importedModelStatus, setImportedModelStatus] = useState<ImportedModelStatus>("idle");
  const [importedModelStatusMessage, setImportedModelStatusMessage] = useState<string | null>(null);
  const [pendingPersistDeviceId, setPendingPersistDeviceId] = useState<string | null>(null);
  const [importedCampusBuildings, setImportedCampusBuildings] = useState<ImportedCampusBuilding[]>([]);
  const [campusImportSummary, setCampusImportSummary] = useState<CampusImportParseResult["summary"] | null>(null);
  const [campusImportError, setCampusImportError] = useState<string | null>(null);
  const [isCampusImporting, setIsCampusImporting] = useState(false);
  const [isPersistingCampus, setIsPersistingCampus] = useState(false);
  const [isPersistingModelAsset, setIsPersistingModelAsset] = useState(false);
  const [selectedBuildingId, setSelectedBuildingId] = useState<string | null>(null);
  const [selectedFloorKey, setSelectedFloorKey] = useState<string | null>(null);
  const [focusSelectedBuildingOnly, setFocusSelectedBuildingOnly] = useState(false);
  const [filterSelectedFloorOnly, setFilterSelectedFloorOnly] = useState(false);
  const [currentModelFile, setCurrentModelFile] = useState<File | null>(null);
  const modelOperation = useRef(0);
  const restoredAsset = useRef<{ id: string; operation: number } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; modelOperation.current += 1; };
  }, []);

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
  const sceneObjectLastSeen = useLiveStore((state) => state.sceneObjectLastSeen);
  const sceneObjectAvailability = useLiveStore((state) => state.sceneObjectAvailability);
  const updateSpatialRefMutation = useUpdateDeviceSpatialRef(token, networkId);
  const campusBuildingsQuery = useCampusBuildings(token, networkId);
  const campusModelAssetsQuery = useCampusModelAssets(token, networkId, assetPage, 20);
  const deviceGroupsQuery = useDeviceGroups(token, networkId);
  const upsertCampusBuildingsMutation = useUpsertCampusBuildings(token, networkId);
  const upsertCampusModelAssetsMutation = useUpsertCampusModelAssets(token, networkId);

  const schematicModel = useTwinSceneModel(baseGraph?.nodes ?? [], baseGraph?.edges ?? [], importSummary?.mappingByDeviceId);
  const alertsQuery = useAlertsQuery(token, { status: "active", networkId: networkId ?? undefined, workspaceId: workspaceId ?? undefined, limit: 200 },
    Boolean(networkId && hasPermission(profile, "read:telemetry")));
  const spatialQuery = useSpatialScene(token, networkId, hasPermission(profile, "read:topology"));
  const sceneModel = useMemo(() => applySpatialScene(schematicModel, spatialQuery.data), [schematicModel, spatialQuery.data]);

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
      state: overlay.state,
      spatial_ref_id: overlay.spatialRefId,
    }));
  }, [sceneModel.overlays]);

  const inspectorNodes = useMemo(() => {
    return sceneModel.nodes
      .map((node) => ({ id: node.id, label: `${node.hostname} (${node.type})` }))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [sceneModel.nodes]);

  const selectedNode = selectedNodeId ? sceneModel.nodeById[selectedNodeId] : null;
  const deviceAlertStates = useMemo(
    () => deriveDeviceAlertStates(alertsQuery.data?.items, liveAlerts, new Set(sceneModel.nodes.map((node) => node.id))),
    [alertsQuery.data?.items, liveAlerts, sceneModel.nodes],
  );
  const alertingDeviceIds = useMemo(() => activeAlertDeviceIds(deviceAlertStates), [deviceAlertStates]);
  const selectedNodeAlerts = selectedNodeId ? deviceAlertStates.get(selectedNodeId) : undefined;

  const selectedNodeScope = useMemo(() => {
    return deriveSpatialBuildingScope(selectedNode?.spatialRefId);
  }, [selectedNode?.spatialRefId]);

  const resolvedBuildingId = selectedBuildingId ?? selectedNodeScope.buildingId;
  const resolvedFloorKey = selectedFloorKey ?? selectedNodeScope.floorKey;
  // Persisted actions never derive scope from a session-only mapping of the selected node.
  const groupFocus = useMemo<GroupFocus>(() => {
    const persistedScope = deriveSpatialBuildingScope(selectedNode?.persistedSpatialRefId);
    return selectedBuildingId
      ? { buildingId: selectedBuildingId, floorKey: selectedFloorKey }
      : { buildingId: persistedScope.buildingId, floorKey: selectedFloorKey ?? persistedScope.floorKey };
  }, [selectedBuildingId, selectedFloorKey, selectedNode?.persistedSpatialRefId]);

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

  const selectedPersistedModelAsset = campusModelAssetsQuery.data?.items.find((item) => item.campus_model_asset_id === selectedAssetId)
    ?? (retainedAsset?.asset.campus_model_asset_id === selectedAssetId ? retainedAsset.asset : undefined);
  const visibleAssets = campusModelAssetsQuery.data?.items ?? [];
  const selectableAssets = selectedPersistedModelAsset && !visibleAssets.some((item) => item.campus_model_asset_id === selectedAssetId)
    ? [selectedPersistedModelAsset, ...visibleAssets] : visibleAssets;
  const selectAsset = (id: string) => {
    setSelectedAssetId(id);
    const asset = visibleAssets.find((item) => item.campus_model_asset_id === id);
    if (asset) setRetainedAsset({ asset, page: assetPage });
    else if (!id) setRetainedAsset(null);
  };

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

  const importCampusGeoJson = useCallback(async (file: File | null) => {
    if (!file) {
      return;
    }

    setIsCampusImporting(true);
    setCampusImportError(null);
    try {
      const parsed = await parseCampusGeoJsonFile(file);
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
    const operation = modelOperation.current;
    const epoch = useLiveStore.getState().epoch;
    try {
      if (importedModelStatus !== "ready") throw new Error("The model must render successfully before it is persisted.");
      // Validated once at import/restore; the same bytes are hashed and natively base64-encoded.
      const model = await loadValidatedModel(currentModelFile);
      const modelBuffer = model.bytes;
      const modelDataBase64 = await encodeBase64(modelBuffer);
      const modelSha256 = await sha256Hex(modelBuffer);
      if (!mounted.current || modelOperation.current !== operation || useLiveStore.getState().epoch !== epoch || useAuthStore.getState().endingSession) return;

      const appliedRegistration = registration?.url === importedModelUrl ? registration.value : null;
      const saved = await upsertCampusModelAssetsMutation.mutateAsync({
        model_file_name: currentModelFile.name,
        model_mime_type: model.mime,
        model_data_base64: modelDataBase64,
        model_sha256: modelSha256,
        model_size_bytes: modelBuffer.byteLength,
        mapping_by_device_id: importSummary.mappingByDeviceId,
        registration: appliedRegistration,
        source: "session_import",
        replace_existing: false,
      });
      if (!mounted.current || modelOperation.current !== operation || useLiveStore.getState().epoch !== epoch) return;
      const receipt = saved.items.find((item) => item.network_id === networkId && item.model_sha256 === modelSha256 && item.model_size_bytes === modelBuffer.byteLength && JSON.stringify(validateRegistration(item.registration)) === JSON.stringify(appliedRegistration));
      if (!receipt) throw new Error("Saved asset receipt mismatch. Reload asset metadata.");
      setRegistration((current) => current === registration && current ? { ...current, saved: true } : current);

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
    registration,
    importedModelUrl,
    importedModelStatus,
    importSummary,
    networkId,
    pushToast,
    token,
    upsertCampusModelAssetsMutation,
  ]);

  const handleConfigureIntentWorkflow = useCallback(async () => {
    if (!selectedNode) {
      navigate("/ops/intent");
      return;
    }

    const handoff = buildIntentHandoffFromNode(selectedNode, selectedNodeAlerts?.alerts ?? []);
    navigate(`/ops/intent?${intentHandoffQuery(handoff)}`);
  }, [navigate, selectedNode, selectedNodeAlerts]);

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

    const operation = ++modelOperation.current;
    if (!mounted.current || operation !== modelOperation.current) return;

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
      // Size, structure and self-contained data: URIs are validated before any object URL exists.
      if (options.replaceModelAsset) await loadValidatedModel(modelFile);
      if (!mounted.current || operation !== modelOperation.current) return;
      const summary = await importModule.parseImportSummary(modelFile, mappingFile, graphNodes);
      if (!mounted.current || operation !== modelOperation.current) return;
      setImportSummary(summary);
      setModelFileName(modelFile.name);
      if (options.replaceModelAsset) {
        setImportedModelUrl(createSessionModelUrl(modelFile));
        setImportedModelStatus("loading");
        setImportedModelStatusMessage(null);
        setCurrentModelFile(modelFile);
      }
    } catch (error) {
      if (mounted.current && operation === modelOperation.current) setImportError(error instanceof Error ? error.message : "Import validation failed.");
    } finally {
      if (mounted.current && operation === modelOperation.current) setIsImporting(false);
    }
  }, [graphNodes]);

  const restorePersistedModel = async () => {
    if (!selectedPersistedModelAsset || !token || !networkId || graphQuery.isFetching || graphQuery.isError || !baseGraph || graphQuery.data?.nextCursor) return;
    if (!window.confirm(`Restore ${selectedPersistedModelAsset.model_file_name} (${selectedAssetId}) locally?${currentModelFile ? " Unsaved model imports and mapping will be replaced." : " Network data will not change."}`)) return;
    const operation = ++modelOperation.current;
    const epoch = useLiveStore.getState().epoch;
    const revision = useLiveStore.getState().topologyRevision;
    setIsImporting(true);
    setImportError(null);
    try {
      const sourcePage = visibleAssets.some((item) => item.campus_model_asset_id === selectedAssetId) ? assetPage : retainedAsset?.page ?? assetPage;
      const [assets, graph] = await Promise.all([
        sourcePage === assetPage ? campusModelAssetsQuery.refetch() : campusModelAssetsQuery.readPage(sourcePage).then((data) => ({ data, isError: false })),
        graphQuery.refetch(),
      ]);
      assetScope.assertCurrent();
      if (!mounted.current || operation !== modelOperation.current || useLiveStore.getState().epoch !== epoch) return;
      if (assets.isError || graph.isError || !graph.data || graph.data.nextCursor) throw new Error("Restore requires a fresh, complete topology and persisted asset read.");
      const asset = assets.data?.items.find((item) => item.campus_model_asset_id === selectedPersistedModelAsset.campus_model_asset_id);
      if (!asset) throw new Error("Persisted model is no longer available. Refresh and try again.");
      const ids = new Set(graph.data.data.nodes.filter((node) => !Object.hasOwn(useLiveStore.getState().topologyTombstones, node.device_id)).map((node) => node.device_id));
      const bytes = asset.storage_backend === "local_cas" || !asset.model_data_base64 ? await downloadModelBytes(asset) : undefined;
      const file = await decodePersistedModel(asset, networkId, ids, bytes);
      const restoredRegistration = validateRegistration(asset.registration);
      assetScope.assertCurrent();
      if (!mounted.current || operation !== modelOperation.current || useLiveStore.getState().epoch !== epoch) return;
      if (useLiveStore.getState().topologyRevision !== revision) throw new Error("Topology changed during restore. Reconcile and try again.");
      const mapping = { ...asset.mapping_by_device_id };
      setImportSummary({ modelFileName: file.name, modelType: file.name.toLowerCase().endsWith(".glb") ? "glb" : "gltf", mappingFileName: null,
        totalRows: Object.keys(mapping).length, matched: Object.keys(mapping).length, unmatched: 0, duplicateKeys: [], mappingByDeviceId: mapping });
      setCurrentModelFile(file);
      setModelFileName(file.name);
      const url = createSessionModelUrl(file);
      setImportedModelUrl(url);
      restoredAsset.current = { id: asset.campus_model_asset_id, operation };
      setRegistration(restoredRegistration ? { url, value: restoredRegistration, saved: true } : null);
      setImportedModelStatus("loading");
      setImportedModelStatusMessage(null);
    } catch (error) {
      if (mounted.current && operation === modelOperation.current) setImportError(error instanceof Error ? error.message : "Model restore failed.");
    } finally {
      if (mounted.current && operation === modelOperation.current) setIsImporting(false);
    }
  };

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
        {graphQuery.data?.nextCursor ? <div role="status">Partial topology: pagination cap reached. Mapping restore and group persistence require a complete graph.</div> : null}
        <QueryState
          query={graphQuery}
          hasData={(data) => data.data.nodes.length > 0 || sceneModel.nodes.length > 0 || Boolean(spatialQuery.data?.objects.some((object) => object.geometry))}
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

              <Suspense fallback={<div style={{ color: "var(--ink-3)" }}>Loading 3D scene...</div>}>
                <TwinScene
                  spatialScene={spatialQuery.data}
                  rfSamples={!spatialQuery.isError && rfImport?.scene === spatialQuery.data ? rfImport?.samples : undefined}
                  nodes={sceneModel.nodes}
                  links={sceneModel.links}
                  measuredPath={measuredPath ?? undefined}
                  overlays={sceneModel.overlays}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  reducedMotion={prefersReducedMotion}
                  layers={layers}
                  alertingDeviceIds={alertingDeviceIds}
                  importedModelUrl={importedModelUrl}
                  modelRegistration={registration?.url === importedModelUrl ? registrationTransform(registration.value) : null}
                  importedCampusBuildings={effectiveCampusBuildings}
                  onImportedModelStatusChange={handleImportedModelStatusChange}
                  buildingViewState={buildingViewState}
                  onSelectBuilding={handleSelectedBuildingChange}
                />
              </Suspense>

              <div className="twin-context-grid">

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
                <p>Authoritative severity: backend alerts. {alertsQuery.isError ? "Backend alerts unavailable." : alertsQuery.isFetching && !alertsQuery.data ? "Loading backend alerts…" : `${alertingDeviceIds.size} devices with active backend alerts.`}</p>
                <p>{VISUAL_HEURISTIC_LABEL} (ring colour, not an alert, never sent as policy) mirrors the backend detector defaults:</p>
                <ul>{DETECTOR_RULE_TEXT.map((line) => <li key={line}>{line}</li>)}</ul>
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
                <p>{sceneModel.nodes.filter((node) => node.placementSource === "canonical").length} canonical device placements. Remaining hash-based positions and live overlay positions are schematic fallback, not measured locations. Campus imports use their separate coordinate frame.</p>
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
                {campusModelAssetsQuery.isFetching ? <p role="status">Loading model assets…</p> : null}
                {campusModelAssetsQuery.isError ? <p role="alert">Model asset list unavailable. Reload to retry.</p> : null}
                {campusModelAssetsQuery.data?.total === 0 ? <p>No persisted model assets.</p> : null}
                <Button tone="ghost" disabled={campusModelAssetsQuery.isFetching || isImporting} onClick={() => void campusModelAssetsQuery.refetch()}>Reload model assets</Button>
                <nav aria-label="Model asset pages">
                  <Button tone="ghost" disabled={assetPage === 1 || campusModelAssetsQuery.isFetching || isImporting} onClick={() => setAssetPage((page) => page - 1)}>Previous asset page</Button>
                  <span role="status">Asset page {assetPage} · {campusModelAssetsQuery.data?.total ?? 0} assets</span>
                  <Button tone="ghost" disabled={!campusModelAssetsQuery.data || assetPage * 20 >= campusModelAssetsQuery.data.total || campusModelAssetsQuery.isFetching || isImporting} onClick={() => setAssetPage((page) => page + 1)}>Next asset page</Button>
                </nav>
                {campusModelAssetsQuery.data && !visibleAssets.length && campusModelAssetsQuery.data.total > 0 ? <p>No assets on this page. Use Previous asset page.</p> : null}
                <p>Available persisted assets; new saves retain earlier assets. Restore changes only the local view.</p>
                {selectedPersistedModelAsset ? (
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                    selected: {selectedPersistedModelAsset.model_file_name} ({selectedPersistedModelAsset.model_size_bytes} bytes)
                    <div>SHA-256: {selectedPersistedModelAsset.model_sha256}</div>
                    <div>Source: {selectedPersistedModelAsset.source ?? "unknown"} · updated {selectedPersistedModelAsset.updated_at}</div>
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
                  <Button type="button" tone="ghost" onClick={restorePersistedModel}
                    disabled={!selectedPersistedModelAsset || !baseGraph || Boolean(graphQuery.data?.nextCursor) || graphQuery.isFetching || graphQuery.isError || isImporting}>
                    {isImporting ? "Validating model..." : "Restore Persisted Model"}
                  </Button>
                </div>
                {importedModelStatusMessage ? (
                  <div role="status" style={{ color: "var(--danger)", fontSize: "0.78rem" }}>
                    {importedModelStatusMessage}
                  </div>
                ) : null}
                {importedModelUrl ? <ModelRegistrationControls key={`${importedModelUrl}:${registration?.saved === true}`} initial={registration?.url === importedModelUrl ? registration.value : null} saved={registration?.url === importedModelUrl && registration.saved} disabled={isPersistingModelAsset} onApply={(value) => { restoredAsset.current = null; setRegistration({ url: importedModelUrl, value, saved: false }); }} /> : null}
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
                    void importCampusGeoJson(event.target.files?.[0] ?? null);
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

              <DeviceGroupsPanel token={token} networkId={networkId} nodes={sceneModel.nodes} focus={groupFocus}
                graphComplete={Boolean(baseGraph) && !graphQuery.data?.nextCursor} graphFetching={graphQuery.isFetching} />

              </div>
            </div>
          )}
        </QueryState>
      </Panel>

      <TwinLifecycleControls networkId={networkId} assets={selectableAssets} selectedId={selectedAssetId} onSelect={selectAsset}
        disabled={isImporting || isPersistingModelAsset || isPersistingCampus}
        onReload={async () => {
          const results = await Promise.all([campusModelAssetsQuery.refetch(), campusBuildingsQuery.refetch(), deviceGroupsQuery.refetch()]);
          return results.every((result) => !result.isError);
        }}
        onRetired={(id) => {
          setSelectedAssetId((current) => current === id ? "" : current);
          setRetainedAsset((current) => current?.asset.campus_model_asset_id === id ? null : current);
          if (restoredAsset.current?.id !== id || restoredAsset.current.operation !== modelOperation.current || registration?.saved === false) return;
          restoredAsset.current = null; modelOperation.current += 1;
          setImportedModelUrl(null); setCurrentModelFile(null); setModelFileName(null); setImportSummary(null); setRegistration(null);
          setImportedModelStatus("idle"); setImportedModelStatusMessage(null);
        }} />
      <Button tone="ghost" aria-expanded={showMeasuredPaths} aria-controls="twin-measured-paths" onClick={() => setShowMeasuredPaths(!showMeasuredPaths)}>{showMeasuredPaths ? "Hide measured probe paths" : "Show measured probe paths"}</Button>
      <Button tone="ghost" aria-expanded={showCustomGroups} onClick={() => { setOpenedCustomGroups(true); setShowCustomGroups(!showCustomGroups); }}>Custom device groups</Button>
      {openedCustomGroups ? <div hidden={!showCustomGroups}><CustomGroupEditor token={token} networkId={networkId} canWrite={hasPermission(profile, "write:config")} /></div> : null}
      {showMeasuredPaths && <div id="twin-measured-paths"><Suspense fallback={<p>Loading probe path panel...</p>}>
        <MeasuredPathPanel nodes={sceneModel.nodes} links={sceneModel.links} onHighlight={setMeasuredPath} />
      </Suspense></div>}

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
                  <Badge text={describeDeviceAlerts(selectedNodeAlerts)} tone={selectedNodeAlerts?.status === "active" ? "danger" : selectedNodeAlerts ? "warn" : "neutral"} />
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.2rem" }}>
                  spatial_ref_id: {selectedNode.spatialRefId ?? "none"}
                </div>
                <div>Position: {selectedNode.placementSource === "canonical" ? `canonical (${selectedNode.spatialObjectId})` : "schematic fallback"} · ({selectedNode.x.toFixed(2)}, {selectedNode.y.toFixed(2)}, {selectedNode.z.toFixed(2)}) m</div>
                <div style={{ marginTop: "0.2rem", display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <Badge text={hasPersistedSpatialRef ? "persisted" : "not persisted"} tone={hasPersistedSpatialRef ? "ok" : "warn"} />
                  {hasImportedSpatialRef ? <Badge text="session import" tone="warn" /> : null}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", marginTop: "0.12rem" }}>
                  {VISUAL_HEURISTIC_LABEL}: {selectedNode.congestion.metrics[0] && !selectedNode.congestion.metrics[0].stale ? `${selectedNode.congestion.metrics[0].metric} ${HEURISTIC_LEVEL_TEXT[selectedNode.congestion.metrics[0].level]}` : "no current detector-covered sample"} (not an alert)
                </div>
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
          <SceneReconciliationStatus />
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
                  <div style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                    Last observed: {sceneObjectLastSeen[sceneObject.id] ? formatTimestamp(new Date(sceneObjectLastSeen[sceneObject.id]).toISOString()) : "unavailable"}. Detail reconciliation: {sceneObjectAvailability[sceneObject.id] ?? "stale"}. Snapshot only, not continuous proof.
                  </div>
                  {sceneObject.status ? (
                    <div style={{ marginTop: "0.2rem" }}>
                      <Badge
                        text={sceneObject.status}
                        tone={overlayTone({ objectType: sceneObject.object_type, status: sceneObject.status, state: sceneObject.state })}
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

      <SpatialScenePanel query={spatialQuery} token={token} networkId={networkId} canWrite={hasPermission(profile, "write:config")} onSelectDevice={setSelectedNodeId} />
      <Button tone="ghost" aria-expanded={showRFImport} onClick={() => setShowRFImport(!showRFImport)}>Operator RF samples</Button>
      {showRFImport ? <Suspense fallback={<p>Loading RF import…</p>}><RFImportPanel scene={spatialQuery.isError ? undefined : spatialQuery.data} workspaceId={workspaceId} networkId={networkId} value={rfImport} onChange={setRFImport} /></Suspense> : null}

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

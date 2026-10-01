import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTopologyGraph } from "@/features/topology/hooks";
import { useCampusModelAssets, useUpsertCampusModelAssets } from "@/features/networks/hooks";
import { useSessionScope } from "@/features/auth/sessionScope";
import { useLiveStore } from "@/features/realtime/store";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useUiStore } from "@/shared/state/ui-store";
import type { AssetRegistration, CampusModelAssetRecord } from "@/shared/types/network";
import { downloadModelBytes } from "./assetDownload";
import { decodePersistedModel, encodeBase64, loadValidatedModel, sha256Hex } from "./modelAsset";
import { registrationTransform, validateRegistration } from "./modelRegistration";
import type { ImportedModelStatus } from "./twinStatusTones";
import * as importModule from "./twinImport";
import type { ImportSummary } from "./twinImport";

export const MODEL_ASSET_PAGE_SIZE = 20;

function createSessionModelUrl(modelFile: File): string {
  if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") return URL.createObjectURL(modelFile);
  return `session-model://${encodeURIComponent(modelFile.name)}`;
}

function revokeSessionModelUrl(modelUrl: string | null): void {
  if (!modelUrl || !modelUrl.startsWith("blob:") || typeof URL === "undefined" || typeof URL.revokeObjectURL !== "function") return;
  URL.revokeObjectURL(modelUrl);
}

interface RegistrationState { url: string; value: AssetRegistration; saved: boolean }

/**
 * Session model import, persisted-asset paging/restore and persistence. Operations are
 * fenced by an operation counter, the realtime epoch and the session scope, so a late
 * result never lands in another network, session or newer operation.
 */
export function useModelAssetWorkflow() {
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const assetScope = useSessionScope();
  const graphQuery = useTopologyGraph(token, networkId);
  const baseGraph = graphQuery.data?.data;
  const [assetPage, setAssetPage] = useState(1);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [retainedAsset, setRetainedAsset] = useState<{ asset: CampusModelAssetRecord; page: number } | null>(null);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [modelFileName, setModelFileName] = useState<string | null>(null);
  const [importedModelUrl, setImportedModelUrl] = useState<string | null>(null);
  const [registration, setRegistration] = useState<RegistrationState | null>(null);
  const [status, setStatus] = useState<ImportedModelStatus>("idle");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [isPersisting, setIsPersisting] = useState(false);
  const [currentModelFile, setCurrentModelFile] = useState<File | null>(null);
  const assetsQuery = useCampusModelAssets(token, networkId, assetPage, MODEL_ASSET_PAGE_SIZE);
  const upsert = useUpsertCampusModelAssets(token, networkId);
  const operation = useRef(0);
  const restoredAsset = useRef<{ id: string; operation: number } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; operation.current += 1; };
  }, []);
  useEffect(() => () => revokeSessionModelUrl(importedModelUrl), [importedModelUrl]);

  const visibleAssets = useMemo(() => assetsQuery.data?.items ?? [], [assetsQuery.data?.items]);
  const selectedAsset = visibleAssets.find((item) => item.campus_model_asset_id === selectedAssetId)
    ?? (retainedAsset?.asset.campus_model_asset_id === selectedAssetId ? retainedAsset.asset : undefined);
  const selectableAssets = selectedAsset && !visibleAssets.some((item) => item.campus_model_asset_id === selectedAssetId) ? [selectedAsset, ...visibleAssets] : visibleAssets;
  const graphNodes = useMemo(() => (baseGraph?.nodes ?? []).map((node) => ({ device_id: node.device_id, spatial_ref_id: node.spatial_ref_id })), [baseGraph?.nodes]);
  const appliedRegistration = registration?.url === importedModelUrl ? registration : null;

  const selectAsset = useCallback((id: string) => {
    setSelectedAssetId(id);
    const asset = visibleAssets.find((item) => item.campus_model_asset_id === id);
    if (asset) setRetainedAsset({ asset, page: assetPage });
    else if (!id) setRetainedAsset(null);
  }, [visibleAssets, assetPage]);

  const importFiles = useCallback(async (modelFile: File | null, mappingFile: File | null, replaceModel: boolean) => {
    if (!modelFile) { setImportError("Select a GLB or GLTF file to import."); return; }
    const current = ++operation.current;
    const extension = importModule.validateModelFile(modelFile);
    if (!extension.ok) { setImportError(extension.message); return; }
    if (mappingFile && !mappingFile.name.toLowerCase().endsWith(".json")) { setImportError("Sidecar mapping must be a JSON file."); return; }
    setIsImporting(true);
    setImportError(null);
    try {
      // Size, structure and self-contained data: URIs are validated before any object URL exists.
      if (replaceModel) await loadValidatedModel(modelFile);
      if (!mounted.current || current !== operation.current) return;
      const summary = await importModule.parseImportSummary(modelFile, mappingFile, graphNodes);
      if (!mounted.current || current !== operation.current) return;
      setImportSummary(summary);
      setModelFileName(modelFile.name);
      if (replaceModel) {
        setImportedModelUrl(createSessionModelUrl(modelFile));
        setStatus("loading");
        setStatusMessage(null);
        setCurrentModelFile(modelFile);
      }
    } catch (error) {
      if (mounted.current && current === operation.current) setImportError(error instanceof Error ? error.message : "Import validation failed.");
    } finally {
      if (mounted.current && current === operation.current) setIsImporting(false);
    }
  }, [graphNodes]);

  const importModelFile = useCallback((file: File | null) => importFiles(file, null, true), [importFiles]);
  const importSidecarFile = useCallback(async (file: File | null) => {
    if (!file) return;
    if (!modelFileName) { setImportError("Upload a GLB/GLTF model first, then upload sidecar mapping JSON."); return; }
    await importFiles(new File([""], modelFileName, { type: "model/gltf-binary" }), file, false);
  }, [importFiles, modelFileName]);

  const canRestore = Boolean(selectedAsset && baseGraph && !graphQuery.data?.nextCursor && !graphQuery.isFetching && !graphQuery.isError && !isImporting);
  const restore = useCallback(async () => {
    if (!selectedAsset || !token || !networkId || graphQuery.isFetching || graphQuery.isError || !baseGraph || graphQuery.data?.nextCursor) return;
    if (!window.confirm(`Restore ${selectedAsset.model_file_name} (${selectedAssetId}) locally?${currentModelFile ? " Unsaved model imports and mapping will be replaced." : " Network data will not change."}`)) return;
    const current = ++operation.current;
    const epoch = useLiveStore.getState().epoch;
    const revision = useLiveStore.getState().topologyRevision;
    setIsImporting(true);
    setImportError(null);
    try {
      const sourcePage = visibleAssets.some((item) => item.campus_model_asset_id === selectedAssetId) ? assetPage : retainedAsset?.page ?? assetPage;
      const [assets, graph] = await Promise.all([
        sourcePage === assetPage ? assetsQuery.refetch() : assetsQuery.readPage(sourcePage).then((data) => ({ data, isError: false })),
        graphQuery.refetch(),
      ]);
      assetScope.assertCurrent();
      if (!mounted.current || current !== operation.current || useLiveStore.getState().epoch !== epoch) return;
      if (assets.isError || graph.isError || !graph.data || graph.data.nextCursor) throw new Error("Restore requires a fresh, complete topology and persisted asset read.");
      const asset = assets.data?.items.find((item) => item.campus_model_asset_id === selectedAsset.campus_model_asset_id);
      if (!asset) throw new Error("Persisted model is no longer available. Refresh and try again.");
      const ids = new Set(graph.data.data.nodes.filter((node) => !Object.hasOwn(useLiveStore.getState().topologyTombstones, node.device_id)).map((node) => node.device_id));
      // C4: metadata pages never carry bytes; download them from the identity-built URL.
      const bytes = asset.storage_backend === "local_cas" || !asset.model_data_base64 ? await downloadModelBytes(asset) : undefined;
      const file = await decodePersistedModel(asset, networkId, ids, bytes);
      const restoredRegistration = validateRegistration(asset.registration);
      assetScope.assertCurrent();
      if (!mounted.current || current !== operation.current || useLiveStore.getState().epoch !== epoch) return;
      if (useLiveStore.getState().topologyRevision !== revision) throw new Error("Topology changed during restore. Reconcile and try again.");
      const mapping = { ...asset.mapping_by_device_id };
      setImportSummary({ modelFileName: file.name, modelType: file.name.toLowerCase().endsWith(".glb") ? "glb" : "gltf", mappingFileName: null,
        totalRows: Object.keys(mapping).length, matched: Object.keys(mapping).length, unmatched: 0, duplicateKeys: [], mappingByDeviceId: mapping });
      setCurrentModelFile(file);
      setModelFileName(file.name);
      const url = createSessionModelUrl(file);
      setImportedModelUrl(url);
      restoredAsset.current = { id: asset.campus_model_asset_id, operation: current };
      setRegistration(restoredRegistration ? { url, value: restoredRegistration, saved: true } : null);
      setStatus("loading");
      setStatusMessage(null);
    } catch (error) {
      if (mounted.current && current === operation.current) setImportError(error instanceof Error ? error.message : "Model restore failed.");
    } finally {
      if (mounted.current && current === operation.current) setIsImporting(false);
    }
  }, [assetPage, assetScope, assetsQuery, baseGraph, currentModelFile, graphQuery, networkId, retainedAsset, selectedAsset, selectedAssetId, token, visibleAssets]);

  const canPersist = Boolean(currentModelFile && importSummary && status === "ready" && !isPersisting && networkId && token);
  const persist = useCallback(async () => {
    if (!networkId || !token || !currentModelFile || !importSummary) return;
    setIsPersisting(true);
    const current = operation.current;
    const epoch = useLiveStore.getState().epoch;
    try {
      if (status !== "ready") throw new Error("The model must render successfully before it is persisted.");
      // Validated once at import/restore; the same bytes are hashed and natively base64-encoded.
      const model = await loadValidatedModel(currentModelFile);
      const modelDataBase64 = await encodeBase64(model.bytes);
      const modelSha256 = await sha256Hex(model.bytes);
      if (!mounted.current || operation.current !== current || useLiveStore.getState().epoch !== epoch || useAuthStore.getState().endingSession) return;
      const applied = appliedRegistration?.value ?? null;
      const saved = await upsert.mutateAsync({
        model_file_name: currentModelFile.name, model_mime_type: model.mime, model_data_base64: modelDataBase64, model_sha256: modelSha256,
        model_size_bytes: model.bytes.byteLength, mapping_by_device_id: importSummary.mappingByDeviceId, registration: applied, source: "session_import", replace_existing: false,
      });
      if (!mounted.current || operation.current !== current || useLiveStore.getState().epoch !== epoch) return;
      // C4: the response is metadata only; the receipt is matched on digest, size and registration.
      const receipt = saved.items.find((item) => item.network_id === networkId && item.model_sha256 === modelSha256 && item.model_size_bytes === model.bytes.byteLength
        && JSON.stringify(validateRegistration(item.registration)) === JSON.stringify(applied));
      if (!receipt) throw new Error("Saved asset receipt mismatch. Reload asset metadata.");
      setRegistration((value) => (value && value === appliedRegistration ? { ...value, saved: true } : value));
      pushToast({ tone: "ok", title: "Campus model asset persisted", description: `${currentModelFile.name} saved for this network.` });
    } catch (error) {
      pushToast({ tone: "danger", title: "Model asset persist failed", description: error instanceof Error ? error.message : "Could not persist model asset." });
    } finally {
      setIsPersisting(false);
    }
  }, [appliedRegistration, currentModelFile, importSummary, networkId, pushToast, status, token, upsert]);

  const onModelStatusChange = useCallback((next: Exclude<ImportedModelStatus, "idle">, message?: string) => {
    setStatus(next);
    setStatusMessage(next === "error" ? message ?? "Could not render the uploaded model." : null);
  }, []);

  const applyRegistration = useCallback((value: AssetRegistration) => {
    if (!importedModelUrl) return;
    restoredAsset.current = null;
    setRegistration({ url: importedModelUrl, value, saved: false });
  }, [importedModelUrl]);

  const onRetired = useCallback((id: string) => {
    setSelectedAssetId((value) => (value === id ? "" : value));
    setRetainedAsset((value) => (value?.asset.campus_model_asset_id === id ? null : value));
    if (restoredAsset.current?.id !== id || restoredAsset.current.operation !== operation.current || registration?.saved === false) return;
    restoredAsset.current = null;
    operation.current += 1;
    setImportedModelUrl(null); setCurrentModelFile(null); setModelFileName(null); setImportSummary(null); setRegistration(null);
    setStatus("idle"); setStatusMessage(null);
  }, [registration?.saved]);

  const modelRegistration = useMemo(() => (appliedRegistration ? registrationTransform(appliedRegistration.value) : null), [appliedRegistration]);

  return {
    assetsQuery, assetPage, setAssetPage, selectedAssetId, selectedAsset, visibleAssets, selectableAssets, selectAsset,
    importSummary, importError, isImporting, importedModelUrl, status, statusMessage, isPersisting, registration: appliedRegistration,
    modelRegistration, sessionMapping: importSummary?.mappingByDeviceId, canPersist, canRestore,
    importModelFile, importSidecarFile, restore, persist, onModelStatusChange, applyRegistration, onRetired,
  };
}

export type ModelAssetWorkflow = ReturnType<typeof useModelAssetWorkflow>;

import { useCallback, useMemo, useRef, useState } from "react";
import { useCampusBuildings, useUpsertCampusBuildings } from "@/features/networks/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useUiStore } from "@/shared/state/ui-store";
import { describeApiError } from "@/shared/lib/errors";
import type { UpsertCampusBuildingInput } from "@/shared/types/network";
import {
  mapImportedBuildingsToCampusBuildings,
  mapPersistedCampusBuildingRecordsToCampusBuildings,
  parseCampusGeoJsonFile,
  type CampusImportParseResult,
  type ImportedCampusBuilding,
} from "./campusImportProvider";
import { DEFAULT_API_BODY_LIMIT_BYTES, diffCampusBuildings, estimateUpsertBytes, toUpsertCampusBuildingInputs, type CampusBuildingDiff } from "./campusBuildingImport";

export interface CampusBuildingsReview {
  inputs: UpsertCampusBuildingInput[];
  diff: CampusBuildingDiff;
  replaceBytes: number;
  mergeBytes: number;
  /** The server returned fewer records than it reported: a replacement could remove unseen buildings. */
  incomplete: boolean;
}

/** GeoJSON import (session) and explicit, reviewed persistence of campus buildings. */
export function useCampusBuildingsWorkflow(showImported: boolean) {
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const query = useCampusBuildings(token, networkId);
  const upsert = useUpsertCampusBuildings(token, networkId);
  const [imported, setImported] = useState<ImportedCampusBuilding[]>([]);
  const [summary, setSummary] = useState<CampusImportParseResult["summary"] | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [persisting, setPersisting] = useState(false);
  const [review, setReview] = useState<CampusBuildingsReview | null>(null);
  const [persistError, setPersistError] = useState<string | null>(null);
  const operation = useRef(0);

  const persisted = useMemo(() => mapPersistedCampusBuildingRecordsToCampusBuildings(query.data?.items ?? []), [query.data?.items]);
  const importedBuildings = useMemo(() => mapImportedBuildingsToCampusBuildings(imported), [imported]);
  const effectiveBuildings = showImported && importedBuildings.length > 0 ? importedBuildings : persisted.length > 0 ? persisted : undefined;

  const importFile = useCallback(async (file: File | null) => {
    if (!file) return;
    const current = ++operation.current;
    setImporting(true);
    setImportError(null);
    setReview(null);
    try {
      const parsed = await parseCampusGeoJsonFile(file);
      if (current !== operation.current) return;
      setImported(parsed.buildings);
      setSummary(parsed.summary);
    } catch (error) {
      if (current !== operation.current) return;
      setImportError(error instanceof Error ? error.message : "Could not parse campus GeoJSON.");
      setImported([]);
      setSummary(null);
    } finally {
      if (current === operation.current) setImporting(false);
    }
  }, []);

  const write = useCallback(async (inputs: UpsertCampusBuildingInput[], replaceExisting: boolean) => {
    setPersisting(true);
    setPersistError(null);
    try {
      await upsert.mutateAsync({ replaceExisting, buildings: inputs });
      setReview(null);
      pushToast({ tone: "ok", title: "Campus buildings persisted", description: `${inputs.length} building records saved for this network${replaceExisting ? " (full replacement)" : " (existing buildings kept)"}.` });
    } catch (error) {
      setPersistError(`${describeApiError(error)} Reload persisted buildings to check the outcome before retrying.`);
    } finally {
      setPersisting(false);
    }
  }, [pushToast, upsert]);

  /**
   * The diff is computed from a fresh read of the persisted list, so the operator confirms
   * the effect against the current server state. Replacing existing buildings always goes
   * through that reviewed diff; with none persisted the import is written directly.
   */
  const requestPersist = useCallback(async () => {
    if (!imported.length || !query.data || query.isError || preparing || persisting) return;
    const current = operation.current;
    setPreparing(true);
    setPersistError(null);
    try {
      const fresh = await query.refetch();
      if (current !== operation.current) return;
      if (fresh.isError || !fresh.data) {
        setPersistError("Could not reload the persisted buildings to compare against. Retry loading buildings, then persist again.");
        return;
      }
      const inputs = toUpsertCampusBuildingInputs(imported);
      if (fresh.data.items.length === 0 && fresh.data.total === 0) {
        await write(inputs, true);
        return;
      }
      setReview({
        inputs,
        diff: diffCampusBuildings(fresh.data.items, inputs),
        replaceBytes: estimateUpsertBytes(inputs, true),
        mergeBytes: estimateUpsertBytes(inputs, false),
        incomplete: fresh.data.total > fresh.data.items.length,
      });
    } finally {
      setPreparing(false);
    }
  }, [imported, persisting, preparing, query, write]);

  const confirmPersist = useCallback((mode: "replace" | "merge") => {
    if (!review || (mode === "replace" && review.incomplete)) return;
    void write(review.inputs, mode === "replace");
  }, [review, write]);

  return {
    query, persisted, imported, summary, importError, importing, preparing, persisting, review, persistError, effectiveBuildings,
    bodyLimitBytes: DEFAULT_API_BODY_LIMIT_BYTES,
    canPersist: imported.length > 0 && Boolean(query.data) && !query.isError && !persisting && Boolean(networkId && token),
    importFile, requestPersist, confirmPersist, cancelReview: () => setReview(null),
  };
}

export type CampusBuildingsWorkflow = ReturnType<typeof useCampusBuildingsWorkflow>;

import { Suspense, lazy, useMemo, useState } from "react";
import "./twin.css";
import { hasPermission } from "@/features/auth/permissions";
import { useDeviceGroups } from "@/features/networks/hooks";
import { usePrefersReducedMotion } from "@/shared/lib/reduced-motion";
import { useAuthStore } from "@/shared/state/auth-store";
import { Panel } from "@/shared/ui/Panel";
import { CampusBuildingsPanel } from "./CampusBuildingsPanel";
import { CampusFocusControls } from "./CampusFocusControls";
import { CampusImportPanel } from "./CampusImportPanel";
import { CustomGroupEditor } from "./CustomGroupEditor";
import { DeviceGroupsPanel } from "./DeviceGroupsPanel";
import { DeviceLegendPanel } from "./DeviceLegendPanel";
import { LiveSceneDeltasPanel, TwinChannelBadges } from "./LiveSceneDeltasPanel";
import { ModelAssetPanel } from "./ModelAssetPanel";
import { RFImportPanel, type RFImportState } from "./RFImportPanel";
import { SpatialScenePanel } from "./SpatialScenePanel";
import { TwinDisclosure } from "./TwinDisclosure";
import { TwinInspectorPanel } from "./TwinInspectorPanel";
import { TwinLayerToolbar } from "./TwinLayerToolbar";
import { CongestionLegendCard, SpatialMappingCard } from "./TwinLegendCards";
import { TwinLifecycleControls } from "./TwinLifecycleControls";
import { TwinViewport } from "./TwinViewport";
import type { MeasuredPathSegment } from "./measuredPathMapping";
import { NEUTRAL_CONGESTION } from "./sceneAdapter";
import { deriveBuildingViewState, deriveGroupFocus, resolveFocus } from "./twinViewState";
import { useCampusBuildingsWorkflow } from "./useCampusBuildingsWorkflow";
import { useModelAssetWorkflow } from "./useModelAssetWorkflow";
import { useTwinSceneData } from "./useTwinSceneData";
import { useTwinViewState } from "./useTwinViewState";

const MeasuredPathPanel = lazy(() => import("./MeasuredPathPanel").then((module) => ({ default: module.MeasuredPathPanel })));

/** Digital Twin page: wires view state, scene data and the persistence workflows to their panels. */
export function TwinPageContent() {
  const canWrite = hasPermission(useAuthStore((state) => state.profile), "write:config");
  const reducedMotion = usePrefersReducedMotion();
  const [view, actions] = useTwinViewState();
  const model = useModelAssetWorkflow();
  const data = useTwinSceneData(model.sessionMapping);
  const campus = useCampusBuildingsWorkflow(view.layers.showImportedBuildings);
  const groupsQuery = useDeviceGroups(data.token, data.networkId);
  const [measuredPath, setMeasuredPath] = useState<MeasuredPathSegment[] | null>(null);
  const [rfImport, setRFImport] = useState<RFImportState | null>(null);
  const { graphQuery, spatialQuery, scene, token, networkId } = data;
  const selectedId = view.selectedNodeId;
  const selectedNode = selectedId ? scene.nodeById[selectedId] ?? null : null;
  const focus = useMemo(() => resolveFocus(view, selectedNode?.spatialRefId), [view, selectedNode?.spatialRefId]);
  const buildingViewState = useMemo(() => deriveBuildingViewState(view, focus), [view, focus]);
  const groupFocus = useMemo(() => deriveGroupFocus(view, selectedNode?.persistedSpatialRefId), [view, selectedNode?.persistedSpatialRefId]);
  const rfSamples = !spatialQuery.isError && rfImport?.scene === spatialQuery.data ? rfImport?.samples : undefined;
  const reloadPersisted = async () => (await Promise.all([model.assetsQuery.refetch(), campus.query.refetch(), groupsQuery.refetch()])).every((result) => !result.isError);

  return (
    <div className="twin-page">
      <Panel title="3D Digital Twin" subtitle="Spatial layout with live overlays" action={<TwinChannelBadges />}>
        <div className="twin-stack">
          {graphQuery.data?.nextCursor ? <p role="status">Partial topology: pagination cap reached. Mapping restore and group persistence require a complete graph.</p> : null}
          <TwinLayerToolbar layers={view.layers} modelAvailable={Boolean(model.importedModelUrl)} onToggle={actions.toggleLayer} />
          <CampusFocusControls nodes={scene.nodes} selectedBuildingId={view.selectedBuildingId} resolvedBuildingId={focus.buildingId}
            selectedFloorKey={view.selectedFloorKey} resolvedFloorKey={focus.floorKey} focusSelectedBuildingOnly={view.focusSelectedBuildingOnly}
            filterSelectedFloorOnly={view.filterSelectedFloorOnly} onSelectedBuildingChange={actions.selectBuilding} onSelectedFloorKeyChange={actions.selectFloor}
            onFocusSelectedBuildingOnlyChange={actions.setFocusBuildingOnly} onFilterSelectedFloorOnlyChange={actions.setFilterFloorOnly} onReset={actions.resetFocus} />
          <DeviceLegendPanel nodes={scene.nodes} />
          <TwinViewport status={data.viewportStatus} onRetry={() => void graphQuery.refetch()} scene={{
            spatialScene: spatialQuery.data, rfSamples, nodes: scene.nodes, links: scene.links, measuredPath: measuredPath ?? undefined,
            overlays: data.overlays, congestionByDevice: data.congestionByDevice, alertingDeviceIds: data.alertingDeviceIds,
            selectedNodeId: selectedId, onSelectNode: actions.selectNode, reducedMotion, layers: view.layers, buildingViewState,
            onSelectBuilding: actions.selectBuilding, importedCampusBuildings: campus.effectiveBuildings, importedModelUrl: model.importedModelUrl,
            modelRegistration: model.modelRegistration, onImportedModelStatusChange: model.onModelStatusChange,
          }} />
          <div className="twin-context-grid">
            <CongestionLegendCard alertsQuery={data.alertsQuery} alertsEnabled={data.alertsEnabled} alertingCount={data.alertingDeviceIds.size} />
            <SpatialMappingCard nodes={scene.nodes} ready={Boolean(data.baseGraph)} />
            <ModelAssetPanel model={model} layerVisible={view.layers.showModel} />
            <CampusBuildingsPanel campus={campus} />
            <DeviceGroupsPanel token={token} networkId={networkId} nodes={scene.nodes} focus={groupFocus} graphComplete={data.graphComplete} graphFetching={Boolean(graphQuery.isFetching)} />
          </div>
        </div>
      </Panel>
      <TwinLifecycleControls networkId={networkId} assets={model.selectableAssets} selectedId={model.selectedAssetId} onSelect={model.selectAsset}
        disabled={model.isImporting || model.isPersisting || campus.persisting} onReload={reloadPersisted} onRetired={model.onRetired} />
      <TwinDisclosure label="Show measured probe paths" openLabel="Hide measured probe paths">
        <Suspense fallback={<p role="status">Loading probe path panel...</p>}>
          <MeasuredPathPanel nodes={scene.nodes} links={scene.links} onHighlight={setMeasuredPath} />
        </Suspense>
      </TwinDisclosure>
      <TwinDisclosure label="Custom device groups" keepMounted>
        <CustomGroupEditor token={token} networkId={networkId} canWrite={canWrite} />
      </TwinDisclosure>
      <div className="twin-two-columns">
        <TwinInspectorPanel token={token} networkId={networkId} nodes={scene.nodes} selectedNode={selectedNode} selectedNodeId={selectedId}
          onSelectNode={actions.selectNode} congestion={(selectedId ? data.congestionByDevice[selectedId] : undefined) ?? NEUTRAL_CONGESTION}
          alerts={selectedId ? data.alertStates.get(selectedId) : undefined} sessionRef={(selectedId ? model.sessionMapping?.[selectedId] : undefined) ?? null} />
        <LiveSceneDeltasPanel overlays={data.overlays} />
      </div>
      <SpatialScenePanel query={spatialQuery} token={token} networkId={networkId} canWrite={canWrite} onSelectDevice={actions.selectNode} />
      <TwinDisclosure label="Operator RF samples">
        <RFImportPanel scene={spatialQuery.isError ? undefined : spatialQuery.data} workspaceId={data.workspaceId} networkId={networkId} value={rfImport} onChange={setRFImport} />
      </TwinDisclosure>
      <CampusImportPanel model={model} />
    </div>
  );
}

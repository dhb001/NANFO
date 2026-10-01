import type { CampusBuildingViewState } from "./campusBuildings";
import { deriveSpatialBuildingScope } from "./campusBuildings";
import type { GroupFocus } from "./groupProposal";

/** UI-only Twin view state: layers, selection and campus focus (no server data). */
export interface TwinLayerState {
  showLinks: boolean;
  showLabels: boolean;
  showCongestion: boolean;
  showOverlays: boolean;
  showModel: boolean;
  showImportedBuildings: boolean;
}

export interface TwinViewState {
  layers: TwinLayerState;
  selectedNodeId: string | null;
  selectedBuildingId: string | null;
  selectedFloorKey: string | null;
  focusSelectedBuildingOnly: boolean;
  filterSelectedFloorOnly: boolean;
}

export type TwinViewAction =
  | { type: "toggleLayer"; layer: keyof TwinLayerState }
  | { type: "selectNode"; nodeId: string | null }
  | { type: "selectBuilding"; buildingId: string | null }
  | { type: "selectFloor"; floorKey: string | null }
  | { type: "setFocusBuildingOnly"; value: boolean }
  | { type: "setFilterFloorOnly"; value: boolean }
  | { type: "resetFocus" };

export const DEFAULT_LAYERS: TwinLayerState = Object.freeze({
  showLinks: true,
  showLabels: true,
  showCongestion: true,
  showOverlays: true,
  showModel: true,
  showImportedBuildings: true,
});

export const INITIAL_VIEW_STATE: TwinViewState = Object.freeze({
  layers: DEFAULT_LAYERS,
  selectedNodeId: null,
  selectedBuildingId: null,
  selectedFloorKey: null,
  focusSelectedBuildingOnly: false,
  filterSelectedFloorOnly: false,
});

export function twinViewReducer(state: TwinViewState, action: TwinViewAction): TwinViewState {
  switch (action.type) {
    case "toggleLayer":
      return { ...state, layers: { ...state.layers, [action.layer]: !state.layers[action.layer] } };
    case "selectNode":
      return state.selectedNodeId === action.nodeId ? state : { ...state, selectedNodeId: action.nodeId };
    case "selectBuilding":
      // A new building invalidates the floor choice and its filter.
      return { ...state, selectedBuildingId: action.buildingId, selectedFloorKey: null, filterSelectedFloorOnly: false };
    case "selectFloor":
      return { ...state, selectedFloorKey: action.floorKey };
    case "setFocusBuildingOnly":
      return { ...state, focusSelectedBuildingOnly: action.value };
    case "setFilterFloorOnly":
      return { ...state, filterSelectedFloorOnly: action.value };
    case "resetFocus":
      return { ...state, selectedBuildingId: null, selectedFloorKey: null, focusSelectedBuildingOnly: false, filterSelectedFloorOnly: false };
    default:
      return state;
  }
}

export interface ResolvedFocus {
  buildingId: string | null;
  floorKey: string | null;
}

/** Explicit focus first, else the selected node's (effective) building/floor. View only. */
export function resolveFocus(state: TwinViewState, selectedNodeSpatialRefId: string | null | undefined): ResolvedFocus {
  const scope = deriveSpatialBuildingScope(selectedNodeSpatialRefId);
  return { buildingId: state.selectedBuildingId ?? scope.buildingId, floorKey: state.selectedFloorKey ?? scope.floorKey };
}

export function deriveBuildingViewState(state: TwinViewState, focus: ResolvedFocus): CampusBuildingViewState | undefined {
  if (!focus.buildingId && !focus.floorKey && !state.focusSelectedBuildingOnly && !state.filterSelectedFloorOnly) return undefined;
  const view: CampusBuildingViewState = {
    selectedBuildingId: focus.buildingId,
    selectedFloorKey: focus.floorKey,
    floorFilterEnabled: state.filterSelectedFloorOnly,
  };
  if (state.focusSelectedBuildingOnly && focus.buildingId) view.visibleBuildingIds = new Set([focus.buildingId]);
  return view;
}

/** Persisted actions never derive scope from a session-only mapping of the selected node. */
export function deriveGroupFocus(state: TwinViewState, selectedNodePersistedRef: string | null | undefined): GroupFocus {
  if (state.selectedBuildingId) return { buildingId: state.selectedBuildingId, floorKey: state.selectedFloorKey };
  const persisted = deriveSpatialBuildingScope(selectedNodePersistedRef);
  return { buildingId: persisted.buildingId, floorKey: state.selectedFloorKey ?? persisted.floorKey };
}

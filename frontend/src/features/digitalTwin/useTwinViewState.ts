import { useCallback, useMemo, useReducer } from "react";
import { INITIAL_VIEW_STATE, twinViewReducer, type TwinLayerState, type TwinViewState } from "./twinViewState";

export interface TwinViewActions {
  toggleLayer: (layer: keyof TwinLayerState) => void;
  selectNode: (nodeId: string | null) => void;
  selectBuilding: (buildingId: string | null) => void;
  selectFloor: (floorKey: string | null) => void;
  setFocusBuildingOnly: (value: boolean) => void;
  setFilterFloorOnly: (value: boolean) => void;
  resetFocus: () => void;
}

/** Layers, selection and building/floor focus as one reducer with stable action callbacks. */
export function useTwinViewState(initial: TwinViewState = INITIAL_VIEW_STATE): [TwinViewState, TwinViewActions] {
  const [state, dispatch] = useReducer(twinViewReducer, initial);
  const toggleLayer = useCallback((layer: keyof TwinLayerState) => dispatch({ type: "toggleLayer", layer }), []);
  const selectNode = useCallback((nodeId: string | null) => dispatch({ type: "selectNode", nodeId }), []);
  const selectBuilding = useCallback((buildingId: string | null) => dispatch({ type: "selectBuilding", buildingId }), []);
  const selectFloor = useCallback((floorKey: string | null) => dispatch({ type: "selectFloor", floorKey }), []);
  const setFocusBuildingOnly = useCallback((value: boolean) => dispatch({ type: "setFocusBuildingOnly", value }), []);
  const setFilterFloorOnly = useCallback((value: boolean) => dispatch({ type: "setFilterFloorOnly", value }), []);
  const resetFocus = useCallback(() => dispatch({ type: "resetFocus" }), []);
  const actions = useMemo(() => ({ toggleLayer, selectNode, selectBuilding, selectFloor, setFocusBuildingOnly, setFilterFloorOnly, resetFocus }),
    [toggleLayer, selectNode, selectBuilding, selectFloor, setFocusBuildingOnly, setFilterFloorOnly, resetFocus]);
  return [state, actions];
}

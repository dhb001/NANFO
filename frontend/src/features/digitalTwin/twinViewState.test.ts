import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { DEFAULT_LAYERS, INITIAL_VIEW_STATE, deriveBuildingViewState, deriveGroupFocus, resolveFocus, twinViewReducer, type TwinViewState } from "./twinViewState";
import { useTwinViewState } from "./useTwinViewState";

const focused: TwinViewState = {
  ...INITIAL_VIEW_STATE,
  selectedBuildingId: "campus-a:building-1",
  selectedFloorKey: "f01",
  focusSelectedBuildingOnly: true,
  filterSelectedFloorOnly: true,
};

describe("twinViewReducer", () => {
  it("toggles one layer at a time and keeps the others", () => {
    const next = twinViewReducer(INITIAL_VIEW_STATE, { type: "toggleLayer", layer: "showCongestion" });
    expect(next.layers).toEqual({ ...DEFAULT_LAYERS, showCongestion: false });
    expect(twinViewReducer(next, { type: "toggleLayer", layer: "showCongestion" }).layers).toEqual(DEFAULT_LAYERS);
  });

  it("returns the same state when the selected node does not change", () => {
    const selected = twinViewReducer(INITIAL_VIEW_STATE, { type: "selectNode", nodeId: "d1" });
    expect(selected.selectedNodeId).toBe("d1");
    expect(twinViewReducer(selected, { type: "selectNode", nodeId: "d1" })).toBe(selected);
    expect(twinViewReducer(selected, { type: "selectNode", nodeId: null }).selectedNodeId).toBeNull();
  });

  it("clears the floor choice and floor filter when the building changes, and resets focus completely", () => {
    const next = twinViewReducer(focused, { type: "selectBuilding", buildingId: "campus-a:building-2" });
    expect(next).toMatchObject({ selectedBuildingId: "campus-a:building-2", selectedFloorKey: null, filterSelectedFloorOnly: false, focusSelectedBuildingOnly: true });
    const reset = twinViewReducer({ ...focused, selectedNodeId: "d1" }, { type: "resetFocus" });
    expect(reset).toEqual({ ...INITIAL_VIEW_STATE, selectedNodeId: "d1" });
  });

  it("sets the floor and the focus/filter flags independently", () => {
    let state = twinViewReducer(INITIAL_VIEW_STATE, { type: "selectFloor", floorKey: "f02" });
    state = twinViewReducer(state, { type: "setFocusBuildingOnly", value: true });
    state = twinViewReducer(state, { type: "setFilterFloorOnly", value: true });
    expect(state).toMatchObject({ selectedFloorKey: "f02", focusSelectedBuildingOnly: true, filterSelectedFloorOnly: true, selectedBuildingId: null });
  });
});

describe("focus derivation", () => {
  it("prefers the explicit building/floor and falls back to the selected node's reference", () => {
    expect(resolveFocus(INITIAL_VIEW_STATE, "campus-a/building-3/f04/rack-1/device-9")).toEqual({ buildingId: "campus-a:building-3", floorKey: "f04" });
    expect(resolveFocus(focused, "campus-a/building-3/f04/rack-1/device-9")).toEqual({ buildingId: "campus-a:building-1", floorKey: "f01" });
    expect(resolveFocus(INITIAL_VIEW_STATE, null)).toEqual({ buildingId: null, floorKey: null });
  });

  it("builds the scene view state only when something is focused", () => {
    expect(deriveBuildingViewState(INITIAL_VIEW_STATE, { buildingId: null, floorKey: null })).toBeUndefined();
    const view = deriveBuildingViewState(focused, resolveFocus(focused, null));
    expect(view).toMatchObject({ selectedBuildingId: "campus-a:building-1", selectedFloorKey: "f01", floorFilterEnabled: true });
    expect([...(view?.visibleBuildingIds ?? [])]).toEqual(["campus-a:building-1"]);
    expect(deriveBuildingViewState({ ...focused, focusSelectedBuildingOnly: false }, resolveFocus(focused, null))?.visibleBuildingIds).toBeUndefined();
  });

  it("derives persisted group scope from the persisted reference, never a session mapping", () => {
    // The node's effective (session) reference points elsewhere; only the persisted one counts.
    expect(deriveGroupFocus(INITIAL_VIEW_STATE, "campus-a/building-1/f01/access/sw-1")).toEqual({ buildingId: "campus-a:building-1", floorKey: "f01" });
    expect(deriveGroupFocus(INITIAL_VIEW_STATE, null)).toEqual({ buildingId: null, floorKey: null });
    expect(deriveGroupFocus({ ...INITIAL_VIEW_STATE, selectedFloorKey: "f09" }, "campus-a/building-1/f01/x")).toEqual({ buildingId: "campus-a:building-1", floorKey: "f09" });
    expect(deriveGroupFocus(focused, "campus-b/building-7/f03/x")).toEqual({ buildingId: "campus-a:building-1", floorKey: "f01" });
  });
});

describe("useTwinViewState", () => {
  it("exposes stable action callbacks backed by the reducer", () => {
    const { result } = renderHook(() => useTwinViewState());
    const actions = result.current[1];
    act(() => actions.selectBuilding("campus-a:building-1"));
    act(() => actions.selectFloor("f01"));
    act(() => actions.toggleLayer("showLinks"));
    expect(result.current[0]).toMatchObject({ selectedBuildingId: "campus-a:building-1", selectedFloorKey: "f01", layers: { ...DEFAULT_LAYERS, showLinks: false } });
    expect(result.current[1]).toBe(actions);
    act(() => actions.resetFocus());
    expect(result.current[0].selectedBuildingId).toBeNull();
  });
});

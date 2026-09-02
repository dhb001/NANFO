import { describe, expect, it } from "vitest";
import {
  buildBuildingByNodeIdIndex,
  deriveBuildingIdFromSpatialRef,
  deriveCampusBuildings,
  deriveSpatialBuildingScope,
  isCampusBuildingVisible,
  isNodeVisibleInBuildingView,
  normalizeFloorKey,
  resolveCampusBuildingCameraFocus,
  resolveCampusBuildingHighlight,
} from "@/features/digitalTwin/campusBuildings";
import type { TwinNode } from "@/features/digitalTwin/sceneAdapter";

function node(id: string, spatialRefId: string | null, x: number, y: number, z: number): TwinNode {
  return {
    id,
    hostname: id,
    type: "switch",
    status: "active",
    x,
    y,
    z,
    spatialRefId,
    congestion: {
      severity: "neutral",
      score: null,
      metrics: [],
      policyVersion: "v2.0.0",
      primaryPolicyId: null,
    },
  };
}

describe("campusBuildings", () => {
  it("derives stable building ids from spatial_ref_id", () => {
    expect(deriveBuildingIdFromSpatialRef("strathmore/sbs/f01/core/rtr-1")).toBe("strathmore:sbs");
    expect(deriveBuildingIdFromSpatialRef("strathmore/ssc/f02/wireless/ap-2")).toBe("strathmore:ssc");
    expect(deriveBuildingIdFromSpatialRef("invalid")).toBeNull();

    expect(
      deriveSpatialBuildingScope("strathmore/sbs/f01/core/rtr-1"),
    ).toEqual({
      campusKey: "strathmore",
      buildingId: "strathmore:sbs",
      floorKey: "f01",
    });
    expect(deriveSpatialBuildingScope("invalid")).toEqual({
      campusKey: null,
      buildingId: null,
      floorKey: null,
    });
    expect(normalizeFloorKey(" F-02 ")).toBe("f-02");
  });

  it("groups nodes by campus/building and derives deterministic metadata", () => {
    const buildings = deriveCampusBuildings([
      node("d-1", "strathmore/sbs/f01/core/d-1", -8, 0, -8),
      node("d-2", "strathmore/sbs/f02/wireless/d-2", -4, 2, -3),
      node("d-3", "strathmore/ssc/f01/services/d-3", 11, 0, 10),
      node("d-4", null, 3, 0, 3),
    ]);

    expect(buildings).toHaveLength(2);

    const sbs = buildings.find((item) => item.id === "strathmore:sbs");
    const ssc = buildings.find((item) => item.id === "strathmore:ssc");

    expect(sbs?.floors).toBe(2);
    expect(sbs?.nodeCount).toBe(2);
    expect(sbs?.metadata.floorKeys).toEqual(["f01", "f02"]);
    expect(sbs?.metadata.nodeIds).toEqual(["d-1", "d-2"]);
    expect(sbs?.footprint.length).toBeGreaterThanOrEqual(4);

    expect(ssc?.floors).toBe(1);
    expect(ssc?.nodeCount).toBe(1);
  });

  it("uses geometry heuristics for box vs extrude", () => {
    const boxBuilding = deriveCampusBuildings([
      node("n-1", "campus/bld-a/f01/core/n-1", 0, 0, 0),
      node("n-2", "campus/bld-a/f01/core/n-2", 1, 0, 1),
    ])[0];

    const extrudeBuilding = deriveCampusBuildings(
      new Array(12).fill(0).map((_, index) =>
        node(
          `x-${index}`,
          `campus/bld-b/f0${(index % 4) + 1}/zone/x-${index}`,
          index,
          index % 3,
          index * 0.8,
        ),
      ),
    )[0];

    expect(boxBuilding.geometry).toBe("box");
    expect(extrudeBuilding.geometry).toBe("extrude");
    expect(extrudeBuilding.footprint.length).toBe(8);
  });

  it("supports visibility/highlight helpers and node index mapping", () => {
    const [building] = deriveCampusBuildings([
      node("n-1", "strathmore/sbs/f01/core/n-1", -2, 0, -1),
      node("n-2", "strathmore/sbs/f02/core/n-2", -1, 2, 0),
    ]);

    expect(isCampusBuildingVisible(building)).toBe(true);
    expect(
      isCampusBuildingVisible(building, {
        visibleBuildingIds: new Set(["other:building"]),
      }),
    ).toBe(false);
    expect(resolveCampusBuildingHighlight(building, { selectedBuildingId: building.id })).toBe("selected");
    expect(resolveCampusBuildingHighlight(building, { selectedBuildingId: "other:building" })).toBe("muted");

    const byNodeId = buildBuildingByNodeIdIndex([building]);
    expect(byNodeId["n-1"]).toBe(building.id);
    expect(byNodeId["n-2"]).toBe(building.id);

    expect(
      isNodeVisibleInBuildingView("strathmore/sbs/f01/core/n-1", {
        selectedBuildingId: "strathmore:sbs",
        selectedFloorKey: "f01",
        floorFilterEnabled: true,
      }),
    ).toBe(true);

    expect(
      isNodeVisibleInBuildingView("strathmore/sbs/f02/core/n-2", {
        selectedBuildingId: "strathmore:sbs",
        selectedFloorKey: "f01",
        floorFilterEnabled: true,
      }),
    ).toBe(false);

    expect(
      isNodeVisibleInBuildingView("strathmore/ssc/f01/core/n-9", {
        selectedBuildingId: "strathmore:sbs",
        selectedFloorKey: "f01",
        floorFilterEnabled: false,
      }),
    ).toBe(true);
  });

  it("resolves deterministic camera focus for building and floor", () => {
    const [building] = deriveCampusBuildings([
      node("n-1", "strathmore/sbs/f01/core/n-1", -4, 0, -3),
      node("n-2", "strathmore/sbs/f03/core/n-2", -1, 2, 0),
    ]);

    const baseFocus = resolveCampusBuildingCameraFocus(building);
    const floorFocus = resolveCampusBuildingCameraFocus(building, { floorKey: "f03" });

    expect(baseFocus.target[0]).toBeCloseTo(building.x, 6);
    expect(baseFocus.target[2]).toBeCloseTo(building.z, 6);
    expect(floorFocus.target[1]).toBeGreaterThan(baseFocus.target[1]);
    expect(floorFocus.position[1]).toBeGreaterThan(baseFocus.position[1] - 0.0001);
  });
});

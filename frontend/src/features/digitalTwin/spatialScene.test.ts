import { describe, expect, it } from "vitest";
import { Vector3 } from "three";
import type { SpatialObject, SpatialScene } from "@/shared/types/spatial";
import { applySpatialScene, EMPTY_SPATIAL_SCENE, parseSpatialScene, spatialWorldTransforms, validateSpatialScene, validateSpatialSnapshot } from "./spatialScene";
import { buildTwinSceneModel } from "./sceneAdapter";

const DEVICE = "00000000-0000-0000-0000-000000000001";
function object(id: string, type: SpatialObject["object_type"], parent: string | null = null): SpatialObject {
  return { object_id: id, object_type: type, parent_id: parent, name: id, position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 }, device_id: null, provenance: { source: "survey", accuracy_m: 0.2 } };
}
function scene(...objects: SpatialObject[]): SpatialScene { return { ...EMPTY_SPATIAL_SCENE, objects }; }

describe("canonical spatial mapping", () => {
  it("composes unordered ancestors using the backend Rz Ry Rx convention (not angle addition)", () => {
    const campus = object("campus", "campus");
    campus.position.x = 10;
    campus.rotation = { x: Math.PI / 2, y: Math.PI / 2, z: 0 };
    const floor = object("floor", "floor", "campus");
    floor.position.y = 2;
    floor.rotation.z = Math.PI / 2;
    const device = object("device", "device", "floor");
    device.position.x = 3;
    const transforms = spatialWorldTransforms(validateSpatialScene(scene(device, floor, campus)));
    const position = new Vector3().setFromMatrixPosition(transforms.get("device")!);
    // floor's 3m local X becomes +3 parent Y; campus Rx then Ry makes +5 world X.
    expect(position.x).toBeCloseTo(15);
    expect(position.y).toBeCloseTo(0);
    expect(position.z).toBeCloseTo(0);
    const direction = new Vector3(1, 0, 0).transformDirection(transforms.get("device")!);
    expect(direction.x).toBeCloseTo(1);
  });

  it("overrides schematic placement, remaps link endpoints and preserves inventory IDs/import references", () => {
    const model = buildTwinSceneModel({ baseNodes: [], baseEdges: [], liveNodesByDeviceId: {
      [DEVICE]: { device_id: DEVICE, hostname: "router", device_type: "router", status: "active" },
    }, telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [], sceneObjects: {}, sceneObjectIdsNewestFirst: [], importedSpatialRefByDeviceId: { [DEVICE]: "import/building/floor" } });
    model.links = [{ id: "edge", sourceId: DEVICE, targetId: DEVICE, source: [0, 0, 0], target: [0, 0, 0], edgeType: "CONNECTED_TO", metadata: {} }];
    const device = object("placement", "device"); device.device_id = DEVICE; device.position = { x: 7, y: 4, z: -2 };
    const mapped = applySpatialScene(model, scene(device));
    expect(mapped.nodeById[DEVICE]).toMatchObject({ id: DEVICE, spatialRefId: "import/building/floor", x: 7, y: 4, z: -2, placementSource: "canonical" });
    expect(mapped.links[0].source).toEqual([7, 4, -2]);
    expect(model.nodes[0].x).not.toBe(7);
    expect(applySpatialScene(model).nodes[0]).toMatchObject({ x: model.nodes[0].x, placementSource: "schematic" });
  });

  it("rejects corrupt hierarchy, duplicate identity, unsupported coordinates and nonfinite/bounded transforms", () => {
    const device = object("d", "device"); device.device_id = DEVICE;
    const cases = [
      scene(device, device), scene({ ...device, parent_id: "missing" }), scene({ ...device, parent_id: "d" }),
      scene(device, { ...device, object_id: "other" }), scene(object("i", "interface")),
      scene({ ...device, position: { x: Infinity, y: 0, z: 0 } }),
      scene({ ...device, rotation: { x: 7, y: 0, z: 0 } }),
      scene({ ...device, device_id: "not-uuid" }), scene({ ...device, name: "\0" }),
      { ...scene(), coordinate_system: { units: "ft", up_axis: "z" } },
    ];
    for (const value of cases) expect(() => validateSpatialScene(value)).toThrow();
    expect(() => validateSpatialSnapshot({ ...scene(), revision: -1 })).toThrow();
    expect(() => parseSpatialScene("{" )).toThrow();
    expect(parseSpatialScene(JSON.stringify({ ...scene(), revision: 99, unknown: 1 }))).toEqual(scene());
  });
});

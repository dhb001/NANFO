import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Matrix4, Vector3 } from "three";
import type { SpatialObject, SpatialSceneSnapshot } from "@/shared/types/spatial";
import { buildSpatialGeometry, floorClipPlane, geometryCameraFocus, geometryDimensions } from "./spatialGeometry";
import { validateSpatialSnapshot } from "./spatialScene";
import { diffSpatialScenes } from "./spatialHistory";
import { parseRFArtifact, rfSpatialHash } from "./rfArtifact";
import { rfFixture, rfFixtureScene } from "./rfFixture.test-data";

function object(type: SpatialObject["object_type"], geometry?: SpatialObject["geometry"], parent: string | null = null): SpatialObject {
  return { object_id: type, object_type: type, parent_id: parent, name: type, device_id: null,
    position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "fixture", accuracy_m: null },
    ...(geometry === undefined ? {} : { geometry }) };
}
function fixture(): SpatialSceneSnapshot {
  return { version: 1, revision: 3, coordinate_system: { units: "m", up_axis: "y" }, objects: [
    object("building", { kind: "box", width: 20, depth: 10, height: 8 }),
    object("floor", { kind: "slab", width: 20, depth: 10, thickness: 0.2 }, "building"),
    object("wall", { kind: "wall", length: 10, height: 3, thickness: 0.2, material: { name: "brick", attenuation_db: null, source: "survey" } }, "floor"),
  ] };
}

describe("dimensioned canonical geometry", () => {
  beforeEach(() => vi.stubGlobal("crypto", webcrypto));
  afterEach(() => vi.unstubAllGlobals());
  it("retains exact shape fields, explicit null and old omitted geometry across validation/restore/hash", async () => {
    const snapshot = fixture();
    expect(validateSpatialSnapshot(snapshot)).toEqual(snapshot);
    // Network/Simulation spatial_document_hash on this exact fixture (Python).
    expect(await rfSpatialHash(snapshot)).toBe("1d7b22578a26834421588d466ed182fde9bbb9f3e7bbea3d58952c6f9f6c7418");
    const old = validateSpatialSnapshot(rfFixtureScene);
    expect(old.objects.every((item) => !Object.hasOwn(item, "geometry"))).toBe(true);
    expect(await rfSpatialHash(old)).toBe(rfFixture.provenance.spatial_document_sha256);
    expect(await parseRFArtifact(JSON.stringify(rfFixture), old, "workspace-1", "network-1", "rf-z-up")).toMatchObject({ receiverId: "rx-1" });
    const explicit = structuredClone(old); explicit.objects[0].geometry = null;
    expect(validateSpatialSnapshot(explicit).objects[0]).toHaveProperty("geometry", null);
    expect(await rfSpatialHash(explicit)).not.toBe(await rfSpatialHash(old));
    const without = structuredClone(snapshot); delete without.objects[0].geometry;
    expect(diffSpatialScenes(snapshot, without).changed).toEqual([{ id: "building", fields: ["geometry"] }]);
    const before = await rfSpatialHash(snapshot);
    const wall = snapshot.objects[2].geometry!;
    if (wall.kind !== "wall") throw new Error("fixture");
    wall.material.source = "changed source";
    expect(await rfSpatialHash(snapshot)).not.toBe(before);
    const hash = await rfSpatialHash(snapshot); wall.thickness *= 2;
    expect(await rfSpatialHash(snapshot)).not.toBe(hash);
  });

  it("rejects malformed unions, dimensions, material and wall hierarchy without coercion", () => {
    const bad = [
      { kind: "box", width: "20", depth: 10, height: 8 },
      { kind: "box", width: 0, depth: 10, height: 8 },
      { kind: "box", width: 1e-7, depth: 10, height: 8 },
      { kind: "box", width: Infinity, depth: 10, height: 8 },
      { kind: "box", width: 1000001, depth: 10, height: 8 },
      { kind: "box", width: 20, depth: 10, height: 8, thickness: 1 },
      { kind: "slab", width: 20, depth: 10, thickness: 1 },
    ];
    for (const geometry of bad) {
      const scene = fixture(); Object.assign(scene.objects[0], { geometry });
      expect(() => validateSpatialSnapshot(scene)).toThrow("geometry");
    }
    for (const material of [{ name: "brick", attenuation_db: -1, source: "survey" }, { name: "brick", attenuation_db: 101, source: "survey" }, { name: "brick", source: "survey" }, { name: "brick", attenuation_db: null, source: " " }]) {
      const scene = fixture(); Object.assign(scene.objects[2].geometry!, { material });
      expect(() => validateSpatialSnapshot(scene)).toThrow("geometry");
    }
    for (const parent of [null, "building", "wall"]) {
      const scene = fixture(); scene.objects[2].parent_id = parent;
      expect(() => validateSpatialSnapshot(scene)).toThrow();
    }
    const scene = fixture(); scene.objects.push(object("device", undefined, "wall"));
    expect(() => validateSpatialSnapshot(scene)).toThrow("hierarchy");
    scene.objects.pop(); scene.objects[2].device_id = "00000000-0000-0000-0000-000000000001";
    expect(() => validateSpatialSnapshot(scene)).toThrow("device");
  });

  it("builds exact local extents and rotated world bounds without inventing shapes", () => {
    expect(geometryDimensions({ kind: "box", width: 20, depth: 10, height: 8 })).toEqual({ size: [20, 8, 10], center: [0, 4, 0] });
    const scene = fixture(); scene.objects[0].position.x = 100; scene.objects[0].rotation.y = Math.PI / 2;
    scene.objects[1].position.y = 4;
    scene.objects.push(object("room", undefined, "floor"));
    const result = buildSpatialGeometry(validateSpatialSnapshot(scene));
    expect(result.shapes).toHaveLength(3);
    expect(result.floorByObject.get("wall")).toBe("floor");
    expect(result.floorByObject.get("room")).toBe("floor");
    const wall = result.shapes[2];
    expect(wall.size).toEqual([10, 3, 0.2]);
    expect(wall.center).toEqual([5, 1.5, 0]);
    expect(wall.bounds.min.x).toBeCloseTo(99.9); expect(wall.bounds.max.x).toBeCloseTo(100.1);
    expect(wall.bounds.min.y).toBeCloseTo(4); expect(wall.bounds.max.y).toBeCloseTo(7);
    expect(wall.bounds.min.z).toBeCloseTo(-10); expect(wall.bounds.max.z).toBeCloseTo(0);
    expect(geometryCameraFocus(result.shapes)?.target).toEqual([100, 4, 0]);
    const small = geometryCameraFocus(result.shapes)!;
    scene.objects[0].geometry = { kind: "box", width: 10000, depth: 10000, height: 10000 };
    const large = geometryCameraFocus(buildSpatialGeometry(scene).shapes)!;
    expect(large.far).toBeGreaterThan(small.far);
    expect(geometryCameraFocus([])).toBeNull();
  });

  it("clips in floor-local Y after translation and tilt, leaving the canonical document untouched", () => {
    const matrix = new Matrix4().makeRotationZ(Math.PI / 2).setPosition(10, 5, 0);
    const [plane] = floorClipPlane(matrix, "2");
    expect(plane.distanceToPoint(new Vector3(0, 1, 0).applyMatrix4(matrix))).toBeCloseTo(1);
    expect(plane.distanceToPoint(new Vector3(0, 3, 0).applyMatrix4(matrix))).toBeCloseTo(-1);
    for (const value of ["", " ", "-1", "1e9", "NaN"]) expect(floorClipPlane(matrix, value)).toEqual([]);
  });
});

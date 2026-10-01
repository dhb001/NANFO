import { describe, expect, it, vi } from "vitest";
import { Box3, BoxGeometry, InstancedMesh, Matrix4, MeshBasicMaterial, Plane, Vector3 } from "three";
import type { SpatialObject, SpatialScene } from "@/shared/types/spatial";
import { buildSpatialGeometry } from "./spatialGeometry";
import { buildCanonicalBatches, canonicalLabels, MAX_CANONICAL_LABELS } from "./canonicalInstances";
import { linkLabelSpecs, linkSegmentPositions, overlayLabelSpecs, MAX_SCENE_OVERLAYS } from "./sceneLayers";
import { buildingLabelSpecs } from "./campusBuildings";
import type { TwinLink, TwinOverlayObject } from "./sceneAdapter";

const edgeIdentity = vi.hoisted(() => ({ calls: 0 }));
vi.mock("@/features/topology/edgeIdentity", async (original) => {
  const actual = await original<typeof import("@/features/topology/edgeIdentity")>();
  return { topologyEdgeIdentity: (edge: Parameters<typeof actual.topologyEdgeIdentity>[0]) => { edgeIdentity.calls += 1; return actual.topologyEdgeIdentity(edge); } };
});
const { buildTwinTopology, orderedEdgeIdentities } = await import("./sceneAdapter");

function object(id: string, type: SpatialObject["object_type"], parent: string | null, geometry?: SpatialObject["geometry"], position = { x: 0, y: 0, z: 0 }): SpatialObject {
  return { object_id: id, object_type: type, parent_id: parent, name: id, device_id: null, position, rotation: { x: 0, y: 0, z: 0 },
    provenance: { source: "fixture", accuracy_m: null }, ...(geometry === undefined ? {} : { geometry }) };
}

function scene(): SpatialScene {
  return { version: 1, coordinate_system: { units: "m", up_axis: "y" }, objects: [
    object("b1", "building", null, { kind: "box", width: 20, depth: 10, height: 8 }, { x: 100, y: 0, z: 0 }),
    object("f1", "floor", "b1", { kind: "slab", width: 20, depth: 10, thickness: 0.2 }),
    object("f2", "floor", "b1", { kind: "slab", width: 20, depth: 10, thickness: 0.2 }, { x: 0, y: 4, z: 0 }),
    object("w1", "wall", "f1", { kind: "wall", length: 10, height: 3, thickness: 0.2, material: { name: "brick", attenuation_db: 10, source: "survey" } }),
    object("w2", "wall", "f2", { kind: "wall", length: 6, height: 3, thickness: 0.2, material: { name: "glass", attenuation_db: null, source: "survey" } }),
    object("r1", "room", "f1", { kind: "box", width: 4, depth: 4, height: 3 }),
  ] };
}

describe("instanced canonical geometry", () => {
  it("groups shapes into one batch per floor and material class", () => {
    const geometry = buildSpatialGeometry(scene());
    const batches = buildCanonicalBatches(geometry.shapes, geometry.floorByObject);
    expect(batches.map((batch) => [batch.key, batch.objectIds])).toEqual([
      ["-|shell", ["b1"]],
      ["f1|shell", ["r1"]],
      ["f1|solid", ["f1"]],
      ["f1|wall", ["w1"]],
      ["f2|solid", ["f2"]],
      ["f2|wall", ["w2"]],
    ]);
  });

  it("maps a unit box to each object's world bounds exactly", () => {
    const geometry = buildSpatialGeometry(scene());
    const batches = buildCanonicalBatches(geometry.shapes, geometry.floorByObject);
    const unit = new BoxGeometry(1, 1, 1);
    for (const batch of batches) {
      const mesh = new InstancedMesh(unit, new MeshBasicMaterial(), batch.objectIds.length);
      mesh.instanceMatrix.array.set(batch.matrices);
      batch.objectIds.forEach((id, index) => {
        const matrix = new Matrix4();
        mesh.getMatrixAt(index, matrix);
        const bounds = new Box3().setFromCenterAndSize(new Vector3(), new Vector3(1, 1, 1)).applyMatrix4(matrix);
        const expected = geometry.shapes.find((shape) => shape.object.object_id === id)!.bounds;
        expect(bounds.min.distanceTo(expected.min)).toBeLessThan(1e-6);
        expect(bounds.max.distanceTo(expected.max)).toBeLessThan(1e-6);
      });
      (mesh.material).dispose();
    }
    unit.dispose();
  });

  it("bounds labels and drops labels cut away by the floor clip plane", () => {
    const geometry = buildSpatialGeometry(scene());
    const labels = canonicalLabels(geometry.shapes, []);
    expect(labels.map((item) => item.id)).toEqual(geometry.shapes.map((shape) => shape.object.object_id));
    expect(labels.find((item) => item.id === "w1")?.text).toBe("w1 · brick · 10 dB · survey");
    expect(labels.find((item) => item.id === "w2")?.text).toBe("w2 · glass · attenuation unknown · survey");
    const cut = canonicalLabels(geometry.shapes, [new Plane(new Vector3(0, -1, 0), 3.5)]);
    expect(cut.map((item) => item.id)).not.toContain("b1");
    expect(canonicalLabels(Array.from({ length: 40 }, () => geometry.shapes[0]), []).length).toBe(MAX_CANONICAL_LABELS);
  });
});

describe("scene layer helpers", () => {
  const link = (id: string): TwinLink => ({ id, source: [0, 1, 2], target: [4, 5, 6], sourceId: "a", targetId: "b", edgeType: "connected_to", metadata: {} });

  it("fills link vertex buffers directly and bounds link labels deterministically", () => {
    expect([...linkSegmentPositions([link("x"), link("y")])]).toEqual([0, 1, 2, 4, 5, 6, 0, 1, 2, 4, 5, 6]);
    const labels = linkLabelSpecs([link("c"), link("a"), link("b")], 2);
    expect(labels.map((item) => [item.id, item.position])).toEqual([["a", [2, 3, 4]], ["b", [2, 3, 4]]]);
  });

  it("caps overlay labels and never labels more overlays than are drawn", () => {
    const overlays: TwinOverlayObject[] = Array.from({ length: MAX_SCENE_OVERLAYS + 20 }, (_, index) => ({ id: `o${index}`, objectType: "intent_state", status: "validated", state: null,
      simulationId: null, intentId: null, spatialRefId: null, x: 0, y: 0, z: 0 }));
    expect(overlayLabelSpecs(overlays)).toHaveLength(24);
    expect(overlayLabelSpecs(overlays, 1000)).toHaveLength(MAX_SCENE_OVERLAYS);
    expect(overlayLabelSpecs(overlays)[0].text).toBe("intent_state validated");
  });

  it("labels at most 24 campus buildings with the selected one first", () => {
    const buildings = Array.from({ length: 30 }, (_, index) => ({ id: `c:b${String(index).padStart(2, "0")}`, campusKey: "c", buildingKey: `b${index}`, label: `B${index}`,
      geometry: "box" as const, x: index, z: 0, baseY: 0, width: 4, depth: 4, height: 6, floors: 2, nodeCount: 0, metadata: { floorKeys: [], nodeIds: [] }, footprint: [] }));
    const labels = buildingLabelSpecs(buildings, { selectedBuildingId: "c:b29" });
    expect(labels).toHaveLength(24);
    expect(labels[0]).toMatchObject({ id: "c:b29", text: "B29 f2 n0 · selected", position: [29, 6.5, 0] });
  });
});

describe("edge identities", () => {
  it("are computed once per edge array (never inside a sort comparator) and reused across rebuilds", () => {
    const edges = Array.from({ length: 300 }, (_, index) => ({ source_id: `n${index % 10}`, target_id: `n${(index + 1) % 10}`, edge_type: "connected_to", metadata: { edge_key: `k${index}` } }));
    const baseNodes = Array.from({ length: 10 }, (_, index) => ({ device_id: `n${index}`, hostname: `n${index}`, device_type: "switch", status: "active", spatial_ref_id: null }));
    edgeIdentity.calls = 0;
    const first = buildTwinTopology({ baseNodes, baseEdges: edges, liveNodesByDeviceId: {} });
    expect(edgeIdentity.calls).toBe(edges.length);
    buildTwinTopology({ baseNodes, baseEdges: edges, liveNodesByDeviceId: { n1: { device_id: "n1", hostname: "live" } } });
    expect(edgeIdentity.calls).toBe(edges.length);
    expect(orderedEdgeIdentities(edges)).toBe(orderedEdgeIdentities(edges));
    expect(first.links.map((item) => item.id)).toEqual([...first.links.map((item) => item.id)].sort());
  });
});

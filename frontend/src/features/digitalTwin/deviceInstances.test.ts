import { describe, expect, it } from "vitest";
import { BoxGeometry, InstancedMesh, Matrix4, MeshBasicMaterial, Raycaster, Vector3 } from "three";
import { buildDeviceBatches, distanceLabelIds, pickedDeviceId, writeDeviceInstances } from "./deviceInstances";
import { deriveDeviceCongestion, type TwinNode } from "./sceneAdapter";
import { resolveDeviceVisual } from "./deviceVisuals";

const node = (id: string, x = 0): TwinNode => ({ id, x, y: 0, z: 0, type: "switch", status: "active", hostname: id, spatialRefId: null, congestion: deriveDeviceCongestion([]) });

describe("device instancing", () => {
  it("batches dense devices while retaining selection, status glow, alerts and congestion rings", () => {
    const nodes = Array.from({ length: 1000 }, (_, i) => node(String(i), i));
    nodes[2].congestion.severity = "high";
    nodes[3].status = "offline";
    const batches = buildDeviceBatches(nodes, "0", new Set(["1"]), true);
    expect(batches).toHaveLength(5);
    for (const batch of batches) for (const item of batch.nodes) expect(batch.visual).toEqual(resolveDeviceVisual({ deviceType: item.type, status: item.status,
      congestionSeverity: item.congestion.severity, selected: item.id === "0", alerting: item.id === "1", colorMode: "type", showCongestionRing: true }));
    expect(buildDeviceBatches(nodes, null, new Set(), false).every((batch) => batch.visual.ringColor === null)).toBe(true);
  });

  it("real Three raycasting resolves the right ID after reorder, movement and deletion", () => {
    const mesh = new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), 3);
    const ray = new Raycaster(new Vector3(10, 0, 5), new Vector3(0, 0, -1));
    let batch = buildDeviceBatches([node("a"), node("b", 10), node("c", 20)], null, new Set(), false)[0];
    writeDeviceInstances(mesh, batch); mesh.updateMatrixWorld(true);
    expect(pickedDeviceId(batch, ray.intersectObject(mesh)[0].instanceId)).toBe("b");
    batch = buildDeviceBatches([node("c", 10), node("a", 50)], null, new Set(), false)[0];
    writeDeviceInstances(mesh, batch);
    expect(mesh.count).toBe(2);
    expect(pickedDeviceId(batch, ray.intersectObject(mesh)[0].instanceId)).toBe("c");
    ray.set(new Vector3(50, 0, 5), new Vector3(0, 0, -1));
    expect(pickedDeviceId(batch, ray.intersectObject(mesh)[0].instanceId)).toBe("a");
    expect(pickedDeviceId(batch, undefined)).toBeNull();
    expect(pickedDeviceId(batch, 2)).toBeNull();
    mesh.geometry.dispose(); (mesh.material as MeshBasicMaterial).dispose(); mesh.dispose();
  });

  it("composes the local ring with device orientation, and culls distant ordinary labels only", () => {
    const rotated = { ...node("rotated"), rotation: [0, 0, Math.PI / 2] as [number, number, number] };
    const batch = buildDeviceBatches([rotated], null, new Set(), true)[0];
    const mesh = new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), 1);
    writeDeviceInstances(mesh, batch, true);
    const matrix = new Matrix4(); mesh.getMatrixAt(0, matrix);
    const position = new Vector3().setFromMatrixPosition(matrix);
    expect(position.x).toBeCloseTo(batch.visual.radius + 0.18);
    expect(position.y).toBeCloseTo(0);
    const nodes = [node("near"), node("far", 1000), node("selected", 2000), node("alert", 3000)];
    expect([...distanceLabelIds(nodes, new Vector3(), "selected", new Set(["alert"]), 3)]).toEqual(["selected", "alert", "near"]);
    expect([...distanceLabelIds(nodes, new Vector3(1000, 0, 0), null, new Set(), 24)]).toEqual(["far"]);
    mesh.geometry.dispose(); (mesh.material as MeshBasicMaterial).dispose(); mesh.dispose();
  });
});

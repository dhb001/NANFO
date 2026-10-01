import { describe, expect, it } from "vitest";
import { BoxGeometry, Color, InstancedMesh, Matrix4, MeshBasicMaterial, Raycaster, Vector3 } from "three";
import { alertOnlyLabelIds, buildDeviceBatches, deviceLabelSpecs, distanceLabelIds, pickedDeviceId, writeDeviceInstances, writeRingColors } from "./deviceInstances";
import { deriveDeviceCongestion, type TwinCongestion, type TwinNode } from "./sceneAdapter";
import { CONGESTION_COLORS, resolveDeviceVisual } from "./deviceVisuals";

const node = (id: string, x = 0): TwinNode => ({ id, x, y: 0, z: 0, type: "switch", status: "active", hostname: id, spatialRefId: null });
const metric = (deviceId: string, value: number) => ({ event_id: deviceId, device_id: deviceId, network_id: "n", workspace_id: "w", metric: "latency_ms", value, unit: "ms",
  observed_at: new Date().toISOString(), source: "emulation", tags: {} });

describe("device instancing", () => {
  it("batches by topology, selection and backend alerts only; telemetry never re-batches", () => {
    const nodes = Array.from({ length: 1000 }, (_, i) => node(String(i), i));
    nodes[3].status = "offline";
    const batches = buildDeviceBatches(nodes, "0", new Set(["1"]));
    expect(batches).toHaveLength(4);
    for (const batch of batches) for (const item of batch.nodes) expect(batch.visual).toEqual(resolveDeviceVisual({ deviceType: item.type, status: item.status,
      congestionSeverity: "neutral", selected: item.id === "0", alerting: item.id === "1", colorMode: "type", showCongestionRing: false }));
    // Same topology/selection/alerts -> identical batching regardless of any telemetry.
    expect(buildDeviceBatches(nodes, "0", new Set(["1"])).map((batch) => [batch.key, batch.nodes.map((item) => item.id)]))
      .toEqual(batches.map((batch) => [batch.key, batch.nodes.map((item) => item.id)]));
    expect(batches.every((batch) => batch.visual.ringColor === null)).toBe(true);
  });

  it("writes visual-heuristic ring colours per instance from the live congestion map", () => {
    const batch = buildDeviceBatches([node("a"), node("b"), node("c")], null, new Set())[0];
    const mesh = new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), 3);
    const congestion: Record<string, TwinCongestion> = { a: deriveDeviceCongestion([metric("a", 150)]), b: deriveDeviceCongestion([metric("b", 80)]) };
    writeRingColors(mesh, batch, congestion);
    const colorAt = (index: number) => { const color = new Color(); mesh.getColorAt(index, color); return color.getHexString(); };
    expect(colorAt(0)).toBe(new Color(CONGESTION_COLORS.high).getHexString());
    expect(colorAt(1)).toBe(new Color(CONGESTION_COLORS.medium).getHexString());
    expect(colorAt(2)).toBe(new Color(CONGESTION_COLORS.neutral).getHexString());
    const version = mesh.instanceColor!.version;
    writeRingColors(mesh, batch, { ...congestion, c: deriveDeviceCongestion([metric("c", 10)]) });
    expect(colorAt(2)).toBe(new Color(CONGESTION_COLORS.low).getHexString());
    expect(mesh.instanceColor!.version).toBeGreaterThan(version);
    mesh.geometry.dispose(); (mesh.material).dispose(); mesh.dispose();
  });

  it("real Three raycasting resolves the right ID after reorder, movement and deletion", () => {
    const mesh = new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), 3);
    const ray = new Raycaster(new Vector3(10, 0, 5), new Vector3(0, 0, -1));
    let batch = buildDeviceBatches([node("a"), node("b", 10), node("c", 20)], null, new Set())[0];
    writeDeviceInstances(mesh, batch); mesh.updateMatrixWorld(true);
    expect(pickedDeviceId(batch, ray.intersectObject(mesh)[0].instanceId)).toBe("b");
    batch = buildDeviceBatches([node("c", 10), node("a", 50)], null, new Set())[0];
    writeDeviceInstances(mesh, batch);
    expect(mesh.count).toBe(2);
    expect(pickedDeviceId(batch, ray.intersectObject(mesh)[0].instanceId)).toBe("c");
    ray.set(new Vector3(50, 0, 5), new Vector3(0, 0, -1));
    expect(pickedDeviceId(batch, ray.intersectObject(mesh)[0].instanceId)).toBe("a");
    expect(pickedDeviceId(batch, undefined)).toBeNull();
    expect(pickedDeviceId(batch, 2)).toBeNull();
    mesh.geometry.dispose(); (mesh.material).dispose(); mesh.dispose();
  });

  it("composes the local ring with device orientation, and culls distant ordinary labels only", () => {
    const rotated = { ...node("rotated"), rotation: [0, 0, Math.PI / 2] as [number, number, number] };
    const batch = buildDeviceBatches([rotated], null, new Set())[0];
    const mesh = new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), 1);
    writeDeviceInstances(mesh, batch, true);
    const matrix = new Matrix4(); mesh.getMatrixAt(0, matrix);
    const position = new Vector3().setFromMatrixPosition(matrix);
    expect(position.x).toBeCloseTo(batch.visual.radius + 0.18);
    expect(position.y).toBeCloseTo(0);
    const nodes = [node("near"), node("far", 1000), node("selected", 2000), node("alert", 3000)];
    expect([...distanceLabelIds(nodes, new Vector3(), "selected", new Set(["alert"]), 3)]).toEqual(["selected", "alert", "near"]);
    expect([...distanceLabelIds(nodes, new Vector3(1000, 0, 0), null, new Set(), 24)]).toEqual(["far"]);
    mesh.geometry.dispose(); (mesh.material).dispose(); mesh.dispose();
  });

  it("labels alerting devices with text, not colour alone", () => {
    const nodes = [node("a"), node("b"), node("c")];
    expect(deviceLabelSpecs(nodes, new Set(["a", "b"]), new Set(["b"]))).toEqual([
      { id: "a", position: [0, 0, 0], text: "a", variant: "device", distanceFactor: 18 },
      { id: "b", position: [0, 0, 0], text: "b · ALERT", variant: "alert", distanceFactor: 18 },
    ]);
  });

  it("keeps bounded ALERT labels when the Labels layer is off", () => {
    const nodes = [node("d"), node("a"), node("c"), node("b")];
    expect([...alertOnlyLabelIds(nodes, new Set(["d", "b", "a", "gone"]), 2)]).toEqual(["a", "b"]);
    expect(alertOnlyLabelIds(nodes, new Set(), 24).size).toBe(0);
    expect(alertOnlyLabelIds(nodes, new Set(["a"]), 0).size).toBe(0);
    expect(deviceLabelSpecs(nodes, alertOnlyLabelIds(nodes, new Set(["c"]), 24), new Set(["c"])).map((label) => label.text)).toEqual(["c · ALERT"]);
  });
});

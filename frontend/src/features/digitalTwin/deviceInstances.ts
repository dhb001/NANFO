import { Euler, Matrix4, Quaternion, Vector3, type InstancedMesh } from "three";
import type { TwinNode } from "./sceneAdapter";
import { resolveDeviceVisual, selectDeviceLabels, type ResolvedDeviceVisual } from "./deviceVisuals";

export interface DeviceBatch { key: string; visual: ResolvedDeviceVisual; nodes: TwinNode[] }

export function buildDeviceBatches(nodes: readonly TwinNode[], selectedId: string | null, alerts: ReadonlySet<string>, showCongestion: boolean): DeviceBatch[] {
  const batches = new Map<string, DeviceBatch>();
  for (const node of nodes) {
    const visual = resolveDeviceVisual({ deviceType: node.type, status: node.status, congestionSeverity: node.congestion.severity,
      selected: node.id === selectedId, alerting: alerts.has(node.id), colorMode: "type", showCongestionRing: showCongestion });
    const key = [visual.definition.geometry, visual.radius, visual.color, visual.emissive, visual.emissiveIntensity, visual.ringColor, visual.outlineColor].join(":");
    const batch = batches.get(key) ?? { key, visual, nodes: [] };
    batch.nodes.push(node);
    batches.set(key, batch);
  }
  return [...batches.values()];
}

/** Index mapping belongs to the same immutable batch used to upload matrices. */
export function pickedDeviceId(batch: DeviceBatch, instanceId: number | undefined): string | null {
  return instanceId !== undefined && Number.isInteger(instanceId) ? batch.nodes[instanceId]?.id ?? null : null;
}

export function writeDeviceInstances(mesh: InstancedMesh, batch: DeviceBatch, ring = false): void {
  const position = new Vector3();
  const rotation = new Quaternion();
  const euler = new Euler();
  const scale = new Vector3(1, 1, 1);
  const matrix = new Matrix4();
  const local = new Matrix4().makeRotationX(-Math.PI / 2);
  local.setPosition(0, -(batch.visual.radius + 0.18), 0);
  batch.nodes.forEach((node, index) => {
    const angles = node.rotation ?? [0, 0, 0];
    rotation.setFromEuler(euler.set(...angles, "XYZ"));
    matrix.compose(position.set(node.x, node.y, node.z), rotation, scale);
    if (ring) matrix.multiply(local);
    mesh.setMatrixAt(index, matrix);
  });
  mesh.count = batch.nodes.length;
  mesh.instanceMatrix.needsUpdate = true;
  // Required after placement, filtering, deletion and regrouping for picking/culling.
  mesh.computeBoundingBox();
  mesh.computeBoundingSphere();
}

export const DEVICE_LABEL_DISTANCE = 65;
export function distanceLabelIds(nodes: readonly TwinNode[], camera: { x: number; y: number; z: number }, selectedId: string | null, alerts: ReadonlySet<string>, maxLabels: number): Set<string> {
  return selectDeviceLabels(nodes.filter((node) => node.id === selectedId || alerts.has(node.id) ||
    (node.x - camera.x) ** 2 + (node.y - camera.y) ** 2 + (node.z - camera.z) ** 2 <= DEVICE_LABEL_DISTANCE ** 2)
    .map((node) => ({ id: node.id, hostname: node.hostname, deviceType: node.type })),
  { maxLabels, selectedNodeId: selectedId, alertingDeviceIds: alerts });
}

import { Color, Euler, Matrix4, Quaternion, Vector3, type InstancedMesh } from "three";
import type { TwinCongestion, TwinNode } from "./sceneAdapter";
import { congestionColor, resolveDeviceVisual, selectDeviceLabels, type ResolvedDeviceVisual } from "./deviceVisuals";
import type { SceneLabelSpec } from "./sceneLabels";

/**
 * Device batches depend on topology, selection and backend alerts only. Telemetry never
 * re-batches or remounts meshes: the visual-heuristic ring colour is a per-instance
 * colour written by `writeRingColors` whenever the congestion map changes.
 */
export interface DeviceBatch { key: string; visual: ResolvedDeviceVisual; nodes: TwinNode[] }

export function buildDeviceBatches(nodes: readonly TwinNode[], selectedId: string | null, alerts: ReadonlySet<string>): DeviceBatch[] {
  const batches = new Map<string, DeviceBatch>();
  for (const node of nodes) {
    const visual = resolveDeviceVisual({ deviceType: node.type, status: node.status, congestionSeverity: "neutral",
      selected: node.id === selectedId, alerting: alerts.has(node.id), colorMode: "type", showCongestionRing: false });
    const key = [visual.definition.geometry, visual.radius, visual.color, visual.emissive, visual.emissiveIntensity, visual.outlineColor].join(":");
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

/** Visual-heuristic ring colours from the live congestion map (neutral when no sample). */
export function writeRingColors(mesh: InstancedMesh, batch: DeviceBatch, congestionByDevice: Readonly<Record<string, TwinCongestion>>): void {
  const color = new Color();
  batch.nodes.forEach((node, index) => {
    mesh.setColorAt(index, color.set(congestionColor(congestionByDevice[node.id]?.severity ?? "neutral")));
  });
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}

export const DEVICE_LABEL_DISTANCE = 65;
export function distanceLabelIds(nodes: readonly TwinNode[], camera: { x: number; y: number; z: number }, selectedId: string | null, alerts: ReadonlySet<string>, maxLabels: number): Set<string> {
  return selectDeviceLabels(nodes.filter((node) => node.id === selectedId || alerts.has(node.id) ||
    (node.x - camera.x) ** 2 + (node.y - camera.y) ** 2 + (node.z - camera.z) ** 2 <= DEVICE_LABEL_DISTANCE ** 2)
    .map((node) => ({ id: node.id, hostname: node.hostname, deviceType: node.type })),
  { maxLabels, selectedNodeId: selectedId, alertingDeviceIds: alerts });
}

/**
 * With the Labels layer off, alerting devices keep their "ALERT" label (bounded, stable
 * id order) so an active backend alert is still not conveyed by colour alone.
 */
export function alertOnlyLabelIds(nodes: readonly TwinNode[], alerts: ReadonlySet<string>, maxLabels: number): Set<string> {
  if (alerts.size === 0 || maxLabels <= 0) return new Set<string>();
  const ids = nodes.filter((node) => alerts.has(node.id)).map((node) => node.id).sort();
  return new Set(ids.slice(0, maxLabels));
}

/** Alerting devices carry a text cue so severity is never conveyed by colour alone. */
export function deviceLabelSpecs(nodes: readonly TwinNode[], ids: ReadonlySet<string>, alerts: ReadonlySet<string>): SceneLabelSpec[] {
  const labels: SceneLabelSpec[] = [];
  for (const node of nodes) {
    if (!ids.has(node.id)) continue;
    const alerting = alerts.has(node.id);
    labels.push({ id: node.id, position: [node.x, node.y, node.z], text: alerting ? `${node.hostname} · ALERT` : node.hostname, variant: alerting ? "alert" : "device", distanceFactor: 18 });
  }
  return labels;
}

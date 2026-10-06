import { Matrix4, Vector3, type Plane } from "three";
import type { GeometryShape } from "./spatialGeometry";
import type { SceneLabelSpec } from "./sceneLabels";

/** Material classes: every shape in a class shares one material and one instanced draw per floor. */
export type CanonicalClass = "shell" | "wall" | "solid";

export const CANONICAL_MATERIALS: Readonly<Record<CanonicalClass, { color: string; opacity: number; depthWrite: boolean }>> = Object.freeze({
  shell: { color: "#47889c", opacity: 0.12, depthWrite: false },
  wall: { color: "#b08462", opacity: 0.65, depthWrite: true },
  solid: { color: "#86928a", opacity: 0.65, depthWrite: true },
});

export const MAX_CANONICAL_LABELS = 24;

export function canonicalClass(shape: GeometryShape): CanonicalClass {
  if (shape.object.object_type === "building" || shape.object.object_type === "room") return "shell";
  return shape.object.geometry?.kind === "wall" ? "wall" : "solid";
}

export interface CanonicalBatch {
  /** `<floor object id | "-">|<class>`: one InstancedMesh, frustum-culled as a unit. */
  key: string;
  floorId: string | null;
  kind: CanonicalClass;
  objectIds: string[];
  /** Column-major 4×4 per instance: world matrix × T(center) × S(size) for a unit box. */
  matrices: Float32Array;
}

export function buildCanonicalBatches(shapes: readonly GeometryShape[], floorByObject: ReadonlyMap<string, string>): CanonicalBatch[] {
  const groups = new Map<string, { floorId: string | null; kind: CanonicalClass; shapes: GeometryShape[] }>();
  for (const shape of shapes) {
    const floorId = floorByObject.get(shape.object.object_id) ?? null;
    const kind = canonicalClass(shape);
    const key = `${floorId ?? "-"}|${kind}`;
    const group = groups.get(key) ?? { floorId, kind, shapes: [] };
    group.shapes.push(shape);
    groups.set(key, group);
  }
  const local = new Matrix4();
  const scale = new Matrix4();
  const instance = new Matrix4();
  return [...groups.entries()]
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, group]) => {
      const matrices = new Float32Array(group.shapes.length * 16);
      group.shapes.forEach((shape, index) => {
        local.makeTranslation(shape.center[0], shape.center[1], shape.center[2]);
        scale.makeScale(shape.size[0], shape.size[1], shape.size[2]);
        instance.multiplyMatrices(shape.matrix, local).multiply(scale);
        instance.toArray(matrices, index * 16);
      });
      return { key, floorId: group.floorId, kind: group.kind, objectIds: group.shapes.map((shape) => shape.object.object_id), matrices };
    });
}

/** Text labels for the first shapes (bounded), anchored at the top centre, hidden when cut away. */
export function canonicalLabels(shapes: readonly GeometryShape[], clippingPlanes: readonly Plane[], limit = MAX_CANONICAL_LABELS): SceneLabelSpec[] {
  const anchor = new Vector3();
  const labels: SceneLabelSpec[] = [];
  for (const [index, shape] of shapes.entries()) {
    if (index >= limit) break;
    anchor.set(shape.center[0], shape.size[1], shape.center[2]).applyMatrix4(shape.matrix);
    if (!clippingPlanes.every((plane) => plane.distanceToPoint(anchor) >= 0)) continue;
    const geometry = shape.object.geometry;
    const material = geometry?.kind === "wall" ? geometry.material : null;
    labels.push({
      id: shape.object.object_id,
      position: [anchor.x, anchor.y, anchor.z],
      text: `${shape.object.name}${material ? ` · ${material.name} · ${material.attenuation_db === null ? "attenuation unknown" : `${material.attenuation_db} dB`} · ${material.source}` : ""}`,
      variant: "geometry",
      distanceFactor: 30,
    });
  }
  return labels;
}

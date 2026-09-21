import { Box3, Matrix4, Plane, Vector3 } from "three";
import type { SpatialGeometry, SpatialObject, SpatialScene } from "@/shared/types/spatial";
import { spatialWorldTransforms } from "./spatialScene";

export type Triple = [number, number, number];
export interface GeometryShape {
  object: SpatialObject;
  matrix: Matrix4;
  size: Triple;
  center: Triple;
  bounds: Box3;
}

/** Dimensions are local meters, independent of rotation. No enclosure inference. */
export function geometryDimensions(g: SpatialGeometry): { size: Triple; center: Triple } {
  const width = g.kind === "wall" ? g.length : g.width;
  const height = g.kind === "slab" ? g.thickness : g.height;
  const depth = g.kind === "box" || g.kind === "slab" ? g.depth : g.thickness;
  return { size: [width, height, depth], center: [g.kind === "wall" ? width / 2 : 0, height / 2, 0] };
}

export function buildSpatialGeometry(scene: SpatialScene) {
  const world = spatialWorldTransforms(scene);
  const byId = new Map(scene.objects.map((object) => [object.object_id, object]));
  const floorByObject = new Map<string, string>();
  for (const object of scene.objects) {
    let ancestor: SpatialObject | undefined = object;
    while (ancestor) {
      if (ancestor.object_type === "floor") { floorByObject.set(object.object_id, ancestor.object_id); break; }
      ancestor = byId.get(ancestor.parent_id ?? "");
    }
  }
  const shapes: GeometryShape[] = scene.objects.flatMap((object) => {
    if (!object.geometry) return [];
    const { size, center } = geometryDimensions(object.geometry);
    const matrix = world.get(object.object_id)!;
    const bounds = new Box3().setFromCenterAndSize(new Vector3(...center), new Vector3(...size)).applyMatrix4(matrix);
    return [{ object, size, center, matrix, bounds }];
  });
  return { shapes, world, floorByObject, floors: scene.objects.filter((object) => object.object_type === "floor") };
}

/** View-only cut plane follows the selected floor's local Y even when tilted. */
export function floorClipPlane(matrix: Matrix4 | undefined, height: string): Plane[] {
  const value = Number(height);
  return matrix && height.trim() && Number.isFinite(value) && value >= 0 && value <= 1_000_000
    ? [new Plane(new Vector3(0, -1, 0), value).applyMatrix4(matrix)] : [];
}

export function geometryCameraFocus(shapes: GeometryShape[]) {
  if (!shapes.length) return null;
  const bounds = shapes.reduce((box, shape) => box.union(shape.bounds), new Box3());
  const target = bounds.getCenter(new Vector3());
  const radius = bounds.getSize(new Vector3()).length() / 2;
  // Conservative fit for 46° FOV, including narrow laptop viewports.
  const distance = Math.max(1, radius * 4);
  return { target: target.toArray() as Triple, position: target.clone().add(new Vector3(1, 0.8, 1).normalize().multiplyScalar(distance)).toArray() as Triple,
    near: Math.max(0.001, distance / 10000), far: Math.max(2000, distance * 10) };
}

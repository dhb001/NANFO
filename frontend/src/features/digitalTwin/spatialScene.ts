import { Euler, Matrix4, Quaternion, Vector3 } from "three";
import type { SpatialObject, SpatialObjectType, SpatialScene, SpatialSceneSnapshot, SpatialVector } from "@/shared/types/spatial";
import type { TwinSceneModel } from "./sceneAdapter";
import { validateSpatialGeometry } from "./spatialGeometryValidation";

export const EMPTY_SPATIAL_SCENE: SpatialScene = { version: 1, coordinate_system: { units: "m", up_axis: "y" }, objects: [] };
export const MAX_SCENE_BYTES = 8 * 1024 * 1024;
const TYPES: SpatialObjectType[] = ["campus", "building", "floor", "room", "rack", "wall", "device", "interface"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a JSON object.");
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 128): string {
  if (typeof value !== "string" || !value.trim() || value.includes("\0") || value.length > max) throw new Error(`Text must be nonblank, NUL-free and at most ${max} characters.`);
  return value;
}
function vector(value: unknown, max: number): SpatialVector {
  const v = record(value);
  if (![v.x, v.y, v.z].every((n) => typeof n === "number" && Number.isFinite(n) && Math.abs(n) <= max)) throw new Error(`Transforms require finite x, y and z numbers within ±${max}.`);
  return { x: v.x as number, y: v.y as number, z: v.z as number };
}

/** Strip unknown fields at the boundary; never pass imported envelope/revision into PUT.scene. */
export function validateSpatialScene(value: unknown): SpatialScene {
  const input = record(value);
  const coordinates = record(input.coordinate_system);
  if (input.version !== 1 || coordinates.units !== "m" || coordinates.up_axis !== "y") throw new Error("Scene requires version 1, meters (m), and y up.");
  if (!Array.isArray(input.objects) || input.objects.length > 10_000) throw new Error("Scene objects must be an array of at most 10000 items.");
  const objects: SpatialObject[] = input.objects.map((value) => {
    const item = record(value);
    const provenance = record(item.provenance);
    const objectType = item.object_type as SpatialObjectType;
    if (!TYPES.includes(objectType)) throw new Error("Unsupported spatial object type.");
    if (item.device_id !== null && (typeof item.device_id !== "string" || !UUID.test(item.device_id))) throw new Error("device_id must be a UUID or null.");
    if (provenance.accuracy_m !== null && (typeof provenance.accuracy_m !== "number" || !Number.isFinite(provenance.accuracy_m) || provenance.accuracy_m < 0 || provenance.accuracy_m > 1_000_000 || provenance.source === "schematic-fallback")) throw new Error("accuracy_m must be 0–1000000 or null; schematic-fallback accuracy must be null.");
    return { object_id: text(item.object_id), parent_id: item.parent_id === null ? null : text(item.parent_id),
      object_type: objectType, name: text(item.name, 256), position: vector(item.position, 1_000_000), rotation: vector(item.rotation, 2 * Math.PI),
      device_id: item.device_id as string | null,
       provenance: { source: text(provenance.source), accuracy_m: provenance.accuracy_m as number | null },
       ...(Object.hasOwn(item, "geometry") ? { geometry: validateSpatialGeometry(item.geometry, objectType) } : {}) };
  });
  const byId = new Map(objects.map((item) => [item.object_id, item]));
  if (byId.size !== objects.length) throw new Error("Duplicate object_id.");
  const deviceIds = new Set<string>();
  for (const item of objects) {
    if (item.device_id !== null) {
      if (item.object_type !== "device" || deviceIds.has(item.device_id.toLowerCase())) throw new Error("Each device UUID may be associated with one device object only.");
      deviceIds.add(item.device_id.toLowerCase());
    }
    if (item.parent_id !== null) {
      const parent = byId.get(item.parent_id);
      if (!parent || parent.object_type === "wall" || TYPES.indexOf(parent.object_type) >= TYPES.indexOf(item.object_type)) throw new Error("Invalid parent hierarchy or cycle.");
    }
    if (item.object_type === "interface" && byId.get(item.parent_id ?? "")?.object_type !== "device") throw new Error("Interfaces require a direct device parent.");
    if (item.object_type === "wall" && !["floor", "room"].includes(byId.get(item.parent_id ?? "")?.object_type ?? "")) throw new Error("Walls require a direct floor or room parent.");
  }
  return { version: 1, coordinate_system: { units: "m", up_axis: "y" }, objects };
}

export function parseSpatialScene(text: string): SpatialScene {
  if (new Blob([text]).size > MAX_SCENE_BYTES) throw new Error("Scene JSON exceeds 8 MiB.");
  return validateSpatialScene(JSON.parse(text));
}

export function validateSpatialSnapshot(value: unknown): SpatialSceneSnapshot {
  const input = record(value);
  if (!Number.isSafeInteger(input.revision) || (input.revision as number) < 0) throw new Error("Invalid scene revision.");
  return { ...validateSpatialScene(input), revision: input.revision as number };
}

export function spatialWorldTransforms(scene: SpatialScene): Map<string, Matrix4> {
  const world = new Map<string, Matrix4>();
  // Validated hierarchy has at most seven levels; parent resolution is order independent.
  const byId = new Map(scene.objects.map((item) => [item.object_id, item]));
  function resolve(item: SpatialObject): Matrix4 {
    const existing = world.get(item.object_id);
    if (existing) return existing;
    const { position: p, rotation: r } = item;
    // Three's intrinsic ZYX is the API's extrinsic X→Y→Z (Rz × Ry × Rx).
    const matrix = new Matrix4().compose(new Vector3(p.x, p.y, p.z), new Quaternion().setFromEuler(new Euler(r.x, r.y, r.z, "ZYX")), new Vector3(1, 1, 1));
    if (item.parent_id !== null) matrix.premultiply(resolve(byId.get(item.parent_id)!));
    world.set(item.object_id, matrix);
    return matrix;
  }
  scene.objects.forEach(resolve);
  return world;
}

export function applySpatialScene(model: TwinSceneModel, scene?: SpatialScene): TwinSceneModel {
  const world = scene ? spatialWorldTransforms(scene) : new Map<string, Matrix4>();
  const placements = new Map(scene?.objects.filter((item) => item.device_id !== null).map((item) => [item.device_id!.toLowerCase(), item]));
  const nodes = model.nodes.map((node) => {
    const object = placements.get(node.id.toLowerCase());
    if (!object) return { ...node, placementSource: "schematic" as const };
    const matrix = world.get(object.object_id)!;
    const position = new Vector3().setFromMatrixPosition(matrix);
    const rotation = new Euler().setFromRotationMatrix(matrix, "XYZ");
    return { ...node, x: position.x, y: position.y, z: position.z, rotation: [rotation.x, rotation.y, rotation.z] as [number, number, number],
      placementSource: "canonical" as const, spatialObjectId: object.object_id };
  });
  const nodeById = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const links = model.links.map((link) => {
    const source = nodeById[link.sourceId];
    const target = nodeById[link.targetId];
    return { ...link, source: [source.x, source.y, source.z] as [number, number, number], target: [target.x, target.y, target.z] as [number, number, number] };
  });
  return { ...model, nodes, nodeById, links };
}

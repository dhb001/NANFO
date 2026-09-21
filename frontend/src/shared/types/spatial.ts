/** ADR-021 v1: local-to-parent meters/radians; column-vector matrix T × Rz × Ry × Rx. */
export interface SpatialVector { x: number; y: number; z: number }
export type SpatialObjectType = "campus" | "building" | "floor" | "room" | "rack" | "wall" | "device" | "interface";
export type SpatialGeometry =
  | { kind: "box"; width: number; depth: number; height: number }
  | { kind: "slab"; width: number; depth: number; thickness: number }
  | { kind: "wall"; length: number; height: number; thickness: number; material: { name: string; attenuation_db: number | null; source: string } };
export interface SpatialObject {
  object_id: string;
  parent_id: string | null;
  object_type: SpatialObjectType;
  name: string;
  position: SpatialVector;
  rotation: SpatialVector;
  device_id: string | null;
  provenance: { source: string; accuracy_m: number | null };
  /** Omission is retained for historical/RF hashes; never default to null. */
  geometry?: SpatialGeometry | null;
}
export interface SpatialScene {
  version: 1;
  coordinate_system: { units: "m"; up_axis: "y" };
  objects: SpatialObject[];
}
export interface SpatialSceneSnapshot extends SpatialScene { revision: number }
export interface PutSpatialScene { expected_revision: number; scene: SpatialScene }

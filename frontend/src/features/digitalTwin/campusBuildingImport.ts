import type { CampusBuildingRecord, UpsertCampusBuildingInput } from "@/shared/types/network";
import type { ImportedCampusBuilding } from "./campusImportProvider";

/** Backend default request body limit (`API_MAX_BODY_BYTES`, 1 MiB); deployments may differ. */
export const DEFAULT_API_BODY_LIMIT_BYTES = 1024 * 1024;

export function toUpsertCampusBuildingInputs(buildings: readonly ImportedCampusBuilding[]): UpsertCampusBuildingInput[] {
  return buildings.map((building) => ({
    building_id: building.id,
    campus_key: building.campusKey,
    building_key: building.buildingKey,
    label: building.label,
    geometry: building.geometry,
    x: building.x,
    z: building.z,
    base_y: building.baseY,
    width: building.width,
    depth: building.depth,
    height: building.height,
    floors: building.floors,
    footprint: building.footprint.map(([x, z]) => [x, z] as [number, number]),
    wall_material: building.wallMaterial,
    attenuation_db: building.attenuationDb,
    source: building.source,
  }));
}

export interface CampusBuildingChange {
  id: string;
  label: string;
  fields: string[];
}

export interface CampusBuildingDiff {
  added: CampusBuildingChange[];
  changed: CampusBuildingChange[];
  unchanged: CampusBuildingChange[];
  /** Persisted buildings absent from the import: soft-deleted by a full replacement. */
  removed: CampusBuildingChange[];
}

const COMPARED_FIELDS = ["label", "geometry", "x", "z", "base_y", "width", "depth", "height", "floors", "footprint", "wall_material", "attenuation_db", "source"] as const;

function same(left: unknown, right: unknown): boolean {
  if (typeof left === "number" && typeof right === "number") return Math.abs(left - right) <= 1e-6 * Math.max(1, Math.abs(left), Math.abs(right));
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((item, index) => same(item, right[index]));
  return (left ?? null) === (right ?? null);
}

/** What a persist would do, so the operator confirms the exact effect before replacing records. */
export function diffCampusBuildings(existing: readonly CampusBuildingRecord[], incoming: readonly UpsertCampusBuildingInput[]): CampusBuildingDiff {
  const persisted = new Map(existing.map((record) => [record.building_id, record]));
  const incomingIds = new Set(incoming.map((item) => item.building_id));
  const diff: CampusBuildingDiff = { added: [], changed: [], unchanged: [], removed: [] };
  for (const item of incoming) {
    const record = persisted.get(item.building_id);
    if (!record) {
      diff.added.push({ id: item.building_id, label: item.label, fields: [] });
      continue;
    }
    const fields = COMPARED_FIELDS.filter((field) => !same(record[field], item[field]));
    (fields.length ? diff.changed : diff.unchanged).push({ id: item.building_id, label: item.label, fields: [...fields] });
  }
  for (const record of existing) {
    if (!incomingIds.has(record.building_id)) diff.removed.push({ id: record.building_id, label: record.label, fields: [] });
  }
  for (const list of Object.values(diff)) list.sort((left: CampusBuildingChange, right: CampusBuildingChange) => left.id.localeCompare(right.id));
  return diff;
}

/** UTF-8 size of the upsert body, to warn before the server's body limit rejects it (413). */
export function estimateUpsertBytes(buildings: readonly UpsertCampusBuildingInput[], replaceExisting: boolean): number {
  return new TextEncoder().encode(JSON.stringify({ buildings, replace_existing: replaceExisting })).byteLength;
}

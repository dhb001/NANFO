import {
  buildCampusBuildingId,
  type CampusBuilding,
  type CampusBuildingGeometryKind,
} from "@/features/digitalTwin/campusBuildings";
import type { CampusBuildingRecord } from "@/shared/types/network";

export interface ImportedCampusBuilding {
  id: string;
  campusKey: string;
  buildingKey: string;
  label: string;
  geometry: CampusBuildingGeometryKind;
  x: number;
  z: number;
  baseY: number;
  width: number;
  depth: number;
  height: number;
  floors: number;
  footprint: Array<[number, number]>;
  wallMaterial: string | null;
  attenuationDb: number | null;
  source: "geojson";
}

export interface CampusImportParseResult {
  buildings: ImportedCampusBuilding[];
  summary: {
    source: "geojson";
    featureCount: number;
    buildingCount: number;
    ignoredCount: number;
  };
}

export interface CampusImportProvider {
  id: string;
  parseGeoJsonText: (value: string) => CampusImportParseResult;
}

interface GeoJsonFeatureCollection {
  type: string;
  features?: unknown;
}

interface GeoJsonFeature {
  type: string;
  properties?: Record<string, unknown>;
  geometry?: {
    type?: string;
    coordinates?: unknown;
  } | null;
}

interface Bounds2D {
  minLon: number;
  maxLon: number;
  minLat: number;
  maxLat: number;
}

const DEFAULT_BASE_Y = -2.3;
const MIN_BUILDING_SPAN = 4;
const MAX_BUILDING_SPAN = 60;
const MIN_HEIGHT = 3.2;
const MAX_HEIGHT = 24;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function normalizeKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9:-]/g, "-")
    .replace(/-+/g, "-");
}

function normalizeLabel(value: string): string {
  const cleaned = value.trim();
  if (!cleaned) {
    return "Building";
  }

  return cleaned
    .split(/[\s_-]+/g)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function readString(record: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string") {
      const cleaned = value.trim();
      if (cleaned) {
        return cleaned;
      }
    }
  }
  return null;
}

function readFiniteNumber(record: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return null;
}

function sanitizeCampusKey(value: string | null): string {
  if (!value) {
    return "campus";
  }
  const normalized = normalizeKey(value);
  return normalized || "campus";
}

function sanitizeBuildingKey(value: string | null, fallbackIndex: number): string {
  if (!value) {
    return `building-${fallbackIndex + 1}`;
  }
  const normalized = normalizeKey(value);
  return normalized || `building-${fallbackIndex + 1}`;
}

function normalizeWallMaterial(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const normalized = normalizeKey(value).replace(/-/g, "_");
  if (!normalized) {
    return null;
  }

  if (normalized.includes("concrete")) {
    return "concrete";
  }
  if (normalized.includes("brick")) {
    return "brick";
  }
  if (normalized.includes("glass")) {
    return "glass";
  }
  if (normalized.includes("drywall") || normalized.includes("gypsum")) {
    return "drywall";
  }
  if (normalized.includes("metal")) {
    return "metal";
  }

  return normalized;
}

function defaultAttenuationForMaterial(wallMaterial: string | null): number | null {
  if (!wallMaterial) {
    return null;
  }
  if (wallMaterial === "concrete") {
    return 14;
  }
  if (wallMaterial === "brick") {
    return 10;
  }
  if (wallMaterial === "glass") {
    return 4;
  }
  if (wallMaterial === "drywall") {
    return 6;
  }
  if (wallMaterial === "metal") {
    return 18;
  }
  return null;
}

function readPolygonCoordinates(feature: GeoJsonFeature): [number, number][] | null {
  if (!feature.geometry || typeof feature.geometry !== "object") {
    return null;
  }

  const geometryType = String(feature.geometry.type ?? "").trim();
  const coordinates = feature.geometry.coordinates;

  if (geometryType === "Polygon" && Array.isArray(coordinates)) {
    const firstRing = coordinates[0];
    if (!Array.isArray(firstRing)) {
      return null;
    }
    const ring = firstRing
      .filter((pair): pair is [number, number] => Array.isArray(pair) && pair.length >= 2)
      .map((pair) => [Number(pair[0]), Number(pair[1])] as [number, number])
      .filter((pair) => Number.isFinite(pair[0]) && Number.isFinite(pair[1]));
    return ring.length >= 3 ? ring : null;
  }

  if (geometryType === "MultiPolygon" && Array.isArray(coordinates)) {
    const firstPolygon = coordinates[0];
    if (!Array.isArray(firstPolygon)) {
      return null;
    }
    const firstRing = firstPolygon[0];
    if (!Array.isArray(firstRing)) {
      return null;
    }
    const ring = firstRing
      .filter((pair): pair is [number, number] => Array.isArray(pair) && pair.length >= 2)
      .map((pair) => [Number(pair[0]), Number(pair[1])] as [number, number])
      .filter((pair) => Number.isFinite(pair[0]) && Number.isFinite(pair[1]));
    return ring.length >= 3 ? ring : null;
  }

  return null;
}

function centroid(points: readonly [number, number][]): [number, number] {
  let sumX = 0;
  let sumY = 0;
  for (const point of points) {
    sumX += point[0];
    sumY += point[1];
  }
  return [sumX / points.length, sumY / points.length];
}

function deriveBounds(features: readonly ImportedCampusBuilding[]): Bounds2D | null {
  if (features.length === 0) {
    return null;
  }

  let minLon = Number.POSITIVE_INFINITY;
  let maxLon = Number.NEGATIVE_INFINITY;
  let minLat = Number.POSITIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;

  for (const feature of features) {
    for (const point of feature.footprint) {
      minLon = Math.min(minLon, point[0]);
      maxLon = Math.max(maxLon, point[0]);
      minLat = Math.min(minLat, point[1]);
      maxLat = Math.max(maxLat, point[1]);
    }
  }

  if (![minLon, maxLon, minLat, maxLat].every(Number.isFinite)) {
    return null;
  }

  return { minLon, maxLon, minLat, maxLat };
}

function mapLonLatToTwinXZ(
  lon: number,
  lat: number,
  bounds: Bounds2D,
): [number, number] {
  const lonSpan = Math.max(0.000001, bounds.maxLon - bounds.minLon);
  const latSpan = Math.max(0.000001, bounds.maxLat - bounds.minLat);

  const xNormalized = (lon - bounds.minLon) / lonSpan;
  const zNormalized = (lat - bounds.minLat) / latSpan;

  const x = (xNormalized - 0.5) * 80;
  const z = (zNormalized - 0.5) * 80;
  return [x, z];
}

function convertFootprintToLocalXZ(
  points: readonly [number, number][],
  centerLon: number,
  centerLat: number,
  bounds: Bounds2D,
): Array<[number, number]> {
  const [centerX, centerZ] = mapLonLatToTwinXZ(centerLon, centerLat, bounds);
  return points.map((pair) => {
    const [x, z] = mapLonLatToTwinXZ(pair[0], pair[1], bounds);
    return [x - centerX, z - centerZ] as [number, number];
  });
}

function spanFromLocalFootprint(points: readonly [number, number][]): {
  width: number;
  depth: number;
} {
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minZ = Number.POSITIVE_INFINITY;
  let maxZ = Number.NEGATIVE_INFINITY;

  for (const point of points) {
    minX = Math.min(minX, point[0]);
    maxX = Math.max(maxX, point[0]);
    minZ = Math.min(minZ, point[1]);
    maxZ = Math.max(maxZ, point[1]);
  }

  return {
    width: clamp(maxX - minX, MIN_BUILDING_SPAN, MAX_BUILDING_SPAN),
    depth: clamp(maxZ - minZ, MIN_BUILDING_SPAN, MAX_BUILDING_SPAN),
  };
}

function pickGeometryKind(localFootprint: readonly [number, number][]): CampusBuildingGeometryKind {
  if (localFootprint.length > 6) {
    return "extrude";
  }
  return "box";
}

function toCampusBuilding(imported: ImportedCampusBuilding): CampusBuilding {
  return {
    id: imported.id,
    campusKey: imported.campusKey,
    buildingKey: imported.buildingKey,
    label: imported.label,
    geometry: imported.geometry,
    x: imported.x,
    z: imported.z,
    baseY: imported.baseY,
    width: imported.width,
    depth: imported.depth,
    height: imported.height,
    floors: imported.floors,
    nodeCount: 0,
    metadata: {
      floorKeys: Array.from({ length: imported.floors }, (_, index) => `f${String(index + 1).padStart(2, "0")}`),
      nodeIds: [],
      wallMaterial: imported.wallMaterial,
      attenuationDb: imported.attenuationDb,
      source: imported.source,
    },
    footprint: imported.footprint,
  };
}

function parseGeoJsonTextDeterministic(value: string): CampusImportParseResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    throw new Error("Campus GeoJSON must contain valid JSON.");
  }

  if (!parsed || typeof parsed !== "object") {
    throw new Error("Campus GeoJSON must be a FeatureCollection object.");
  }

  const collection = parsed as GeoJsonFeatureCollection;
  if (String(collection.type) !== "FeatureCollection" || !Array.isArray(collection.features)) {
    throw new Error("Campus GeoJSON must be a FeatureCollection with a features array.");
  }

  const imported: ImportedCampusBuilding[] = [];
  let ignoredCount = 0;

  for (const [index, rawFeature] of collection.features.entries()) {
    const feature = rawFeature as GeoJsonFeature;
    if (!feature || typeof feature !== "object" || feature.type !== "Feature") {
      ignoredCount += 1;
      continue;
    }

    const properties = (feature.properties ?? {}) as Record<string, unknown>;

    const allowed = readString(properties, ["building", "amenity", "use"]);
    if (!allowed || allowed === "no") {
      ignoredCount += 1;
      continue;
    }

    const ring = readPolygonCoordinates(feature);
    if (!ring) {
      ignoredCount += 1;
      continue;
    }

    const buildingName =
      readString(properties, ["name", "building:name", "building_name"]) ??
      readString(properties, ["ref", "id"]) ??
      `building-${index + 1}`;
    const campusName = readString(properties, ["campus", "site", "site_name"]) ?? "campus";

    const floorCountRaw = readFiniteNumber(properties, ["building:levels", "levels", "floors"]);
    const floorCount = clamp(Math.round(floorCountRaw ?? 1), 1, 16);

    const wallMaterial = normalizeWallMaterial(readString(properties, ["material", "wall_material", "building:material"]));
    const attenuationDbRaw = readFiniteNumber(properties, ["attenuation_db", "rf_attenuation_db"]);
    const attenuationDb = attenuationDbRaw ?? defaultAttenuationForMaterial(wallMaterial);

    imported.push({
      id: buildCampusBuildingId(sanitizeCampusKey(campusName), sanitizeBuildingKey(buildingName, index)),
      campusKey: sanitizeCampusKey(campusName),
      buildingKey: sanitizeBuildingKey(buildingName, index),
      label: normalizeLabel(buildingName),
      geometry: "box",
      x: 0,
      z: 0,
      baseY: DEFAULT_BASE_Y,
      width: MIN_BUILDING_SPAN,
      depth: MIN_BUILDING_SPAN,
      height: MIN_HEIGHT,
      floors: floorCount,
      footprint: ring,
      wallMaterial,
      attenuationDb: attenuationDb === null ? null : clamp(attenuationDb, 0, 40),
      source: "geojson",
    });
  }

  const bounds = deriveBounds(imported);
  if (!bounds) {
    return {
      buildings: [],
      summary: {
        source: "geojson",
        featureCount: collection.features.length,
        buildingCount: 0,
        ignoredCount: collection.features.length,
      },
    };
  }

  const normalized = imported
    .map((building) => {
      const [centerLon, centerLat] = centroid(building.footprint);
      const [centerX, centerZ] = mapLonLatToTwinXZ(centerLon, centerLat, bounds);
      const localFootprint = convertFootprintToLocalXZ(building.footprint, centerLon, centerLat, bounds);
      const span = spanFromLocalFootprint(localFootprint);

      const nextFootprint =
        localFootprint.length >= 3
          ? localFootprint
          : [
              [-span.width / 2, -span.depth / 2],
              [span.width / 2, -span.depth / 2],
              [span.width / 2, span.depth / 2],
              [-span.width / 2, span.depth / 2],
            ];

      return {
        ...building,
        x: centerX,
        z: centerZ,
        width: span.width,
        depth: span.depth,
        height: clamp(building.floors * 2.9 + 1.6, MIN_HEIGHT, MAX_HEIGHT),
        geometry: pickGeometryKind(nextFootprint),
        footprint: nextFootprint,
      } satisfies ImportedCampusBuilding;
    })
    .sort((left, right) => left.id.localeCompare(right.id));

  const deduped: ImportedCampusBuilding[] = [];
  const seen = new Set<string>();
  for (const building of normalized) {
    if (seen.has(building.id)) {
      ignoredCount += 1;
      continue;
    }
    seen.add(building.id);
    deduped.push(building);
  }

  return {
    buildings: deduped,
    summary: {
      source: "geojson",
      featureCount: collection.features.length,
      buildingCount: deduped.length,
      ignoredCount,
    },
  };
}

export const DETERMINISTIC_CAMPUS_IMPORT_PROVIDER: CampusImportProvider = {
  id: "deterministic.geojson.osm.v1",
  parseGeoJsonText: parseGeoJsonTextDeterministic,
};

export function parseCampusGeoJson(value: string): CampusImportParseResult {
  return DETERMINISTIC_CAMPUS_IMPORT_PROVIDER.parseGeoJsonText(value);
}

export function mapImportedBuildingsToCampusBuildings(
  buildings: readonly ImportedCampusBuilding[],
): CampusBuilding[] {
  return [...buildings]
    .map(toCampusBuilding)
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function mapPersistedCampusBuildingRecordsToCampusBuildings(
  records: readonly CampusBuildingRecord[],
): CampusBuilding[] {
  return [...records]
    .map((record) => {
      const floors = Math.max(1, Number(record.floors) || 1);
      return {
        id: record.building_id,
        campusKey: record.campus_key,
        buildingKey: record.building_key,
        label: record.label,
        geometry: record.geometry,
        x: record.x,
        z: record.z,
        baseY: record.base_y,
        width: record.width,
        depth: record.depth,
        height: record.height,
        floors,
        nodeCount: 0,
        metadata: {
          floorKeys: Array.from({ length: floors }, (_, index) => `f${String(index + 1).padStart(2, "0")}`),
          nodeIds: [],
          wallMaterial: record.wall_material,
          attenuationDb: record.attenuation_db,
          source: record.source,
        },
        footprint: (record.footprint ?? []).map((point) => [point[0], point[1]] as [number, number]),
      } satisfies CampusBuilding;
    })
    .sort((left, right) => left.id.localeCompare(right.id));
}

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
  /** Local metres relative to (x, z): [east, south] i.e. Twin [x, z]. */
  footprint: Array<[number, number]>;
  wallMaterial: string | null;
  attenuationDb: number | null;
  source: "geojson";
}

export interface CampusProjection {
  kind: "local-equirectangular";
  originLon: number;
  originLat: number;
  /** Largest vertex distance from the origin, metres. */
  extentMeters: number;
}

export interface CampusImportParseResult {
  buildings: ImportedCampusBuilding[];
  summary: {
    source: "geojson";
    featureCount: number;
    buildingCount: number;
    ignoredCount: number;
    projection: CampusProjection | null;
    warnings: string[];
  };
}

export interface CampusImportProvider {
  id: string;
  parseGeoJsonText: (value: string) => CampusImportParseResult;
}

/** Backend validation limits (backend/app/modules/network/schemas.py UpsertCampusBuilding*). */
export const CAMPUS_BACKEND_LIMITS = Object.freeze({
  buildingsPerRequest: 1000,
  buildingIdLength: 160,
  campusKeyLength: 120,
  buildingKeyLength: 120,
  labelLength: 160,
  wallMaterialLength: 64,
  floorsMin: 1,
  floorsMax: 128,
  attenuationDbMin: 0,
  attenuationDbMax: 80,
});

/** Client caps checked before any parsing work. */
export const MAX_CAMPUS_GEOJSON_BYTES = 8 * 1024 * 1024;
export const MAX_CAMPUS_FEATURES = CAMPUS_BACKEND_LIMITS.buildingsPerRequest;
export const MAX_RING_VERTICES = 2_000;
export const MAX_TOTAL_VERTICES = 200_000;
/** Equirectangular error stays negligible at campus scale; larger extracts are rejected. */
export const MAX_CAMPUS_EXTENT_M = 25_000;
const MAX_ORIGIN_ABS_LAT = 85;
/** IUGG mean Earth radius (metres). */
export const EARTH_MEAN_RADIUS_M = 6_371_008.8;

const DEFAULT_BASE_Y = -2.3;
/** Schematic storey height when a feature carries no explicit height (not measured). */
const SCHEMATIC_STOREY_M = 2.9;
const SCHEMATIC_ROOF_M = 1.6;
/** Backend requires width/depth/height > 0; degenerate footprints get this floor only. */
const MIN_POSITIVE_SPAN_M = 0.1;

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
  if (!cleaned) return "Building";
  const label = cleaned
    .split(/[\s_-]+/g)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
  return label.length > CAMPUS_BACKEND_LIMITS.labelLength ? `${label.slice(0, CAMPUS_BACKEND_LIMITS.labelLength - 1)}…` : label;
}

function readString(record: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string") {
      const cleaned = value.trim();
      if (cleaned) return cleaned;
    }
  }
  return null;
}

function readFiniteNumber(record: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
      const parsed = Number.parseFloat(value);
      if (Number.isFinite(parsed) && /^\s*[-+]?\d*\.?\d+(?:e[-+]?\d+)?\s*(?:m)?\s*$/i.test(value)) return parsed;
    }
  }
  return null;
}

function sanitizeCampusKey(value: string | null): string {
  return (value ? normalizeKey(value) : "") || "campus";
}

function sanitizeBuildingKey(value: string | null, fallbackIndex: number): string {
  return (value ? normalizeKey(value) : "") || `building-${fallbackIndex + 1}`;
}

function normalizeWallMaterial(value: string | null): string | null {
  if (!value) return null;
  const normalized = normalizeKey(value).replace(/-/g, "_");
  if (!normalized) return null;
  if (normalized.includes("concrete")) return "concrete";
  if (normalized.includes("brick")) return "brick";
  if (normalized.includes("glass")) return "glass";
  if (normalized.includes("drywall") || normalized.includes("gypsum")) return "drywall";
  if (normalized.includes("metal")) return "metal";
  return normalized;
}

/** Operator-documented defaults for common wall materials (dB per wall). */
function defaultAttenuationForMaterial(wallMaterial: string | null): number | null {
  switch (wallMaterial) {
    case "concrete": return 14;
    case "brick": return 10;
    case "glass": return 4;
    case "drywall": return 6;
    case "metal": return 18;
    default: return null;
  }
}

function readRing(value: unknown): [number, number][] | null {
  if (!Array.isArray(value) || value.length > MAX_RING_VERTICES + 1) return null;
  const ring: [number, number][] = [];
  for (const pair of value) {
    if (!Array.isArray(pair) || pair.length < 2) return null;
    const lon = Number(pair[0]);
    const lat = Number(pair[1]);
    // WGS84 longitude/latitude only (RFC 7946); projected coordinates are rejected.
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) return null;
    ring.push([lon, lat]);
  }
  if (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) ring.pop();
  return ring.length >= 3 ? ring : null;
}

function readPolygonCoordinates(feature: GeoJsonFeature): [number, number][] | null {
  if (!feature.geometry || typeof feature.geometry !== "object") return null;
  const geometryType = String(feature.geometry.type ?? "").trim();
  const coordinates = feature.geometry.coordinates;
  if (geometryType === "Polygon" && Array.isArray(coordinates)) return readRing(coordinates[0]);
  if (geometryType === "MultiPolygon" && Array.isArray(coordinates) && Array.isArray(coordinates[0])) return readRing(coordinates[0][0]);
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

/**
 * Local equirectangular projection about `origin` with cos(latitude) correction.
 * Twin axes: +x east, +z south (three.js y-up, right-handed: north is -z), metres.
 */
export function projectLonLat(lon: number, lat: number, originLon: number, originLat: number): [number, number] {
  const radians = Math.PI / 180;
  const east = (lon - originLon) * radians * Math.cos(originLat * radians) * EARTH_MEAN_RADIUS_M;
  const north = (lat - originLat) * radians * EARTH_MEAN_RADIUS_M;
  return [east, north === 0 ? 0 : -north];
}

/** A box is exact only for axis-aligned rectangles; every other footprint is extruded. */
function isAxisAlignedRectangle(points: readonly [number, number][]): boolean {
  if (points.length !== 4) return false;
  const tolerance = 0.05;
  return points.every(([x, z], index) => {
    const [nextX, nextZ] = points[(index + 1) % points.length];
    return Math.abs(nextX - x) <= tolerance || Math.abs(nextZ - z) <= tolerance;
  });
}

interface Candidate {
  campusKey: string;
  buildingKey: string;
  label: string;
  floors: number;
  explicitHeight: number | null;
  wallMaterial: string | null;
  attenuationDb: number | null;
  ring: [number, number][];
}

function parseGeoJsonTextDeterministic(value: string): CampusImportParseResult {
  if (value.length > MAX_CAMPUS_GEOJSON_BYTES) throw new Error("Campus GeoJSON exceeds 8 MiB.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    throw new Error("Campus GeoJSON must contain valid JSON.");
  }
  if (!parsed || typeof parsed !== "object") throw new Error("Campus GeoJSON must be a FeatureCollection object.");
  const collection = parsed as GeoJsonFeatureCollection;
  if (String(collection.type) !== "FeatureCollection" || !Array.isArray(collection.features)) {
    throw new Error("Campus GeoJSON must be a FeatureCollection with a features array.");
  }
  if (collection.features.length > MAX_CAMPUS_FEATURES) {
    throw new Error(`Campus GeoJSON has ${collection.features.length} features; at most ${MAX_CAMPUS_FEATURES} are supported per import.`);
  }

  const warnings = new Map<string, number>();
  const warn = (message: string) => warnings.set(message, (warnings.get(message) ?? 0) + 1);
  const candidates: Candidate[] = [];
  let ignoredCount = 0;
  let totalVertices = 0;

  for (const [index, rawFeature] of collection.features.entries()) {
    const feature = rawFeature as GeoJsonFeature;
    if (!feature || typeof feature !== "object" || feature.type !== "Feature") {
      ignoredCount += 1;
      continue;
    }
    const properties = (feature.properties && typeof feature.properties === "object" ? feature.properties : {}) as Record<string, unknown>;
    const allowed = readString(properties, ["building", "amenity", "use"]);
    if (!allowed || allowed === "no") {
      ignoredCount += 1;
      continue;
    }
    const ring = readPolygonCoordinates(feature);
    if (!ring) {
      ignoredCount += 1;
      warn("features without a valid WGS84 polygon ring were ignored");
      continue;
    }
    totalVertices += ring.length;
    if (totalVertices > MAX_TOTAL_VERTICES) throw new Error(`Campus GeoJSON exceeds ${MAX_TOTAL_VERTICES} polygon vertices.`);

    const buildingName =
      readString(properties, ["name", "building:name", "building_name"]) ??
      readString(properties, ["ref", "id"]) ??
      `building-${index + 1}`;
    const campusKey = sanitizeCampusKey(readString(properties, ["campus", "site", "site_name"]));
    const buildingKey = sanitizeBuildingKey(buildingName, index);
    if (campusKey.length > CAMPUS_BACKEND_LIMITS.campusKeyLength || buildingKey.length > CAMPUS_BACKEND_LIMITS.buildingKeyLength ||
        buildCampusBuildingId(campusKey, buildingKey).length > CAMPUS_BACKEND_LIMITS.buildingIdLength) {
      ignoredCount += 1;
      warn(`features whose campus/building identifier exceeds the backend limit (${CAMPUS_BACKEND_LIMITS.buildingIdLength} characters) were ignored`);
      continue;
    }

    const floorsRaw = readFiniteNumber(properties, ["building:levels", "levels", "floors"]);
    let floors = floorsRaw === null ? 1 : Math.round(floorsRaw);
    if (floorsRaw !== null && (floors < CAMPUS_BACKEND_LIMITS.floorsMin || floors > CAMPUS_BACKEND_LIMITS.floorsMax)) {
      warn(`floor counts outside ${CAMPUS_BACKEND_LIMITS.floorsMin}–${CAMPUS_BACKEND_LIMITS.floorsMax} were replaced by 1`);
      floors = 1;
    }
    const heightRaw = readFiniteNumber(properties, ["height", "building:height"]);
    const explicitHeight = heightRaw !== null && heightRaw > 0 ? heightRaw : null;
    if (heightRaw !== null && explicitHeight === null) warn("non-positive heights were replaced by the schematic storey height");

    let wallMaterial = normalizeWallMaterial(readString(properties, ["material", "wall_material", "building:material"]));
    if (wallMaterial && wallMaterial.length > CAMPUS_BACKEND_LIMITS.wallMaterialLength) {
      warn(`wall materials longer than ${CAMPUS_BACKEND_LIMITS.wallMaterialLength} characters were dropped`);
      wallMaterial = null;
    }
    const attenuationRaw = readFiniteNumber(properties, ["attenuation_db", "rf_attenuation_db"]);
    let attenuationDb = attenuationRaw ?? defaultAttenuationForMaterial(wallMaterial);
    if (attenuationDb !== null && (attenuationDb < CAMPUS_BACKEND_LIMITS.attenuationDbMin || attenuationDb > CAMPUS_BACKEND_LIMITS.attenuationDbMax)) {
      warn(`attenuation values outside ${CAMPUS_BACKEND_LIMITS.attenuationDbMin}–${CAMPUS_BACKEND_LIMITS.attenuationDbMax} dB were dropped (unknown)`);
      attenuationDb = null;
    }

    candidates.push({ campusKey, buildingKey, label: normalizeLabel(buildingName), floors, explicitHeight, wallMaterial, attenuationDb, ring });
  }

  const summaryBase = { source: "geojson" as const, featureCount: collection.features.length };
  const warningList = () => [...warnings.entries()].map(([message, count]) => `${count} ${message}`);
  if (candidates.length === 0) {
    return { buildings: [], summary: { ...summaryBase, buildingCount: 0, ignoredCount: collection.features.length, projection: null, warnings: warningList() } };
  }

  const [originLon, originLat] = centroid(candidates.map((candidate) => centroid(candidate.ring)));
  if (Math.abs(originLat) > MAX_ORIGIN_ABS_LAT) throw new Error("Campus GeoJSON is too close to a pole for a local projection.");
  let extentMeters = 0;
  const projected = candidates.map((candidate) => {
    const points = candidate.ring.map(([lon, lat]) => projectLonLat(lon, lat, originLon, originLat));
    for (const [x, z] of points) extentMeters = Math.max(extentMeters, Math.hypot(x, z));
    return { candidate, points };
  });
  if (extentMeters > MAX_CAMPUS_EXTENT_M) {
    throw new Error(`Campus GeoJSON spans more than ${MAX_CAMPUS_EXTENT_M / 1000} km from its centroid; import a campus-scale extract.`);
  }

  const normalized = projected
    .map(({ candidate, points }) => {
      const [centerX, centerZ] = centroid(points);
      const footprint = points.map(([x, z]) => [x - centerX, z - centerZ] as [number, number]);
      let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
      for (const [x, z] of footprint) {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
      }
      return {
        id: buildCampusBuildingId(candidate.campusKey, candidate.buildingKey),
        campusKey: candidate.campusKey,
        buildingKey: candidate.buildingKey,
        label: candidate.label,
        geometry: isAxisAlignedRectangle(footprint) ? "box" : "extrude",
        x: centerX,
        z: centerZ,
        baseY: DEFAULT_BASE_Y,
        width: Math.max(MIN_POSITIVE_SPAN_M, maxX - minX),
        depth: Math.max(MIN_POSITIVE_SPAN_M, maxZ - minZ),
        height: candidate.explicitHeight ?? candidate.floors * SCHEMATIC_STOREY_M + SCHEMATIC_ROOF_M,
        floors: candidate.floors,
        footprint,
        wallMaterial: candidate.wallMaterial,
        attenuationDb: candidate.attenuationDb,
        source: "geojson",
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
      ...summaryBase,
      buildingCount: deduped.length,
      ignoredCount,
      projection: { kind: "local-equirectangular", originLon, originLat, extentMeters },
      warnings: warningList(),
    },
  };
}

export const DETERMINISTIC_CAMPUS_IMPORT_PROVIDER: CampusImportProvider = {
  id: "deterministic.geojson.osm.v2-local-metric",
  parseGeoJsonText: parseGeoJsonTextDeterministic,
};

export function parseCampusGeoJson(value: string): CampusImportParseResult {
  return DETERMINISTIC_CAMPUS_IMPORT_PROVIDER.parseGeoJsonText(value);
}

function isGeoJsonName(file: Pick<File, "name" | "type">) {
  const lowerName = file.name.toLowerCase();
  const mime = file.type.toLowerCase();
  return lowerName.endsWith(".json") || lowerName.endsWith(".geojson") || mime.includes("application/json") || mime.includes("application/geo+json");
}

async function readText(file: Blob): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Campus file cannot be read."));
    reader.readAsText(file);
  });
}

/** File entry point: type and size caps are enforced before the file is read or parsed. */
export async function parseCampusGeoJsonFile(file: File): Promise<CampusImportParseResult> {
  if (!isGeoJsonName(file)) throw new Error("Campus file must be .geojson or .json.");
  if (file.size > MAX_CAMPUS_GEOJSON_BYTES) throw new Error("Campus GeoJSON exceeds 8 MiB.");
  return parseCampusGeoJson(await readText(file));
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

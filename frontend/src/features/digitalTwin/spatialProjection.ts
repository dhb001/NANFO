export interface SpatialRefPath {
  raw: string;
  normalized: string;
  segments: string[];
  campus: string | null;
  building: string | null;
  floor: string | null;
  rack: string | null;
  device: string | null;
}

export interface SpatialPlacement {
  x: number;
  y: number;
  z: number;
  mode: "spatial_ref" | "hash_fallback";
  parsedPath: SpatialRefPath | null;
}

export interface SpatialProjectionProvider {
  id: string;
  parseSpatialRefPath: (spatialRefId: string | null | undefined) => SpatialRefPath | null;
  projectPlacement: (spatialRefId: string | null | undefined, fallbackSeed: string) => SpatialPlacement;
}

function hashPosition(seed: string, axis: number) {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash << 5) - hash + seed.charCodeAt(index) + axis * 17;
    hash |= 0;
  }
  const normalized = Math.sin(hash) * 0.5 + 0.5;
  return normalized * 36 - 18;
}

function hashRange(seed: string, min: number, max: number) {
  const unit = hashPosition(seed, 7) / 36 + 0.5;
  return min + unit * (max - min);
}

function cleanSpatialSegment(value: string) {
  return value.trim().replace(/\s+/g, "-");
}

function parseFloorIndex(floor: string | null): number | null {
  if (!floor) {
    return null;
  }

  const numericMatch = floor.match(/-?\d+/);
  if (!numericMatch) {
    return null;
  }

  const parsed = Number(numericMatch[0]);
  if (!Number.isFinite(parsed)) {
    return null;
  }

  return parsed;
}

function parseSpatialRefPathDeterministic(spatialRefId: string | null | undefined): SpatialRefPath | null {
  if (!spatialRefId) {
    return null;
  }

  const cleaned = spatialRefId.trim();
  if (!cleaned) {
    return null;
  }

  const segments = cleaned
    .split("/")
    .map(cleanSpatialSegment)
    .filter(Boolean);

  if (segments.length === 0) {
    return null;
  }

  const normalized = segments.join("/");
  return {
    raw: cleaned,
    normalized,
    segments,
    campus: segments[0] ?? null,
    building: segments[1] ?? null,
    floor: segments[2] ?? null,
    rack: segments[3] ?? null,
    device: segments[4] ?? segments[segments.length - 1] ?? null,
  };
}

function projectPlacementDeterministic(
  spatialRefId: string | null | undefined,
  fallbackSeed: string,
): SpatialPlacement {
  const parsedPath = parseSpatialRefPathDeterministic(spatialRefId);
  if (!parsedPath) {
    return {
      x: hashPosition(fallbackSeed, 1),
      y: hashPosition(fallbackSeed, 2) * 0.22,
      z: hashPosition(fallbackSeed, 3),
      mode: "hash_fallback",
      parsedPath: null,
    };
  }

  const extras = parsedPath.segments.slice(5).join("/");
  const floorIndex = parseFloorIndex(parsedPath.floor);
  const floorY =
    floorIndex !== null
      ? floorIndex * 2.6 - 2.6
      : hashRange(`floor:${parsedPath.normalized}`, -1.6, 4.8);

  const x =
    hashRange(`campus-x:${parsedPath.campus ?? ""}`, -12, 12) +
    hashRange(`building-x:${parsedPath.building ?? ""}`, -6, 6) +
    hashRange(`rack-x:${parsedPath.rack ?? ""}`, -2.4, 2.4) +
    hashRange(`device-x:${parsedPath.device ?? fallbackSeed}`, -0.85, 0.85) +
    hashRange(`extras-x:${extras}`, -0.5, 0.5);

  const z =
    hashRange(`campus-z:${parsedPath.campus ?? ""}`, -12, 12) +
    hashRange(`building-z:${parsedPath.building ?? ""}`, -6, 6) +
    hashRange(`rack-z:${parsedPath.rack ?? ""}`, -2.4, 2.4) +
    hashRange(`device-z:${parsedPath.device ?? fallbackSeed}`, -0.85, 0.85) +
    hashRange(`extras-z:${extras}`, -0.5, 0.5);

  return {
    x,
    y: floorY + hashRange(`device-y:${parsedPath.device ?? fallbackSeed}`, -0.4, 0.4),
    z,
    mode: "spatial_ref",
    parsedPath,
  };
}

export const DETERMINISTIC_SPATIAL_PROJECTION_PROVIDER: SpatialProjectionProvider = {
  id: "deterministic.spatial_ref.v1",
  parseSpatialRefPath: parseSpatialRefPathDeterministic,
  projectPlacement: projectPlacementDeterministic,
};

export function parseSpatialRefPath(spatialRefId: string | null | undefined): SpatialRefPath | null {
  return DETERMINISTIC_SPATIAL_PROJECTION_PROVIDER.parseSpatialRefPath(spatialRefId);
}

export function deriveDeterministicPlacement(
  spatialRefId: string | null | undefined,
  fallbackSeed: string,
): SpatialPlacement {
  return DETERMINISTIC_SPATIAL_PROJECTION_PROVIDER.projectPlacement(spatialRefId, fallbackSeed);
}

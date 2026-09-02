import type { TwinNode } from "@/features/digitalTwin/sceneAdapter";
import { parseSpatialRefPath } from "@/features/digitalTwin/spatialProjection";

export type CampusBuildingGeometryKind = "box" | "extrude";

export interface CampusBuilding {
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
  nodeCount: number;
  metadata: {
    floorKeys: string[];
    nodeIds: string[];
    wallMaterial?: string | null;
    attenuationDb?: number | null;
    source?: string | null;
  };
  footprint: Array<[number, number]>;
}

export interface DeriveCampusBuildingsOptions {
  maxBuildings?: number;
  baseY?: number;
}

export interface CampusBuildingViewState {
  selectedBuildingId?: string | null;
  selectedFloorKey?: string | null;
  floorFilterEnabled?: boolean;
  visibleBuildingIds?: ReadonlySet<string>;
  hiddenBuildingIds?: ReadonlySet<string>;
  campusFilter?: string | null;
}

export type CampusBuildingHighlightState = "default" | "selected" | "muted";

interface BuildingScope {
  id: string;
  campusKey: string;
  buildingKey: string;
  floorKey: string | null;
}

export interface SpatialBuildingScope {
  campusKey: string | null;
  buildingId: string | null;
  floorKey: string | null;
}

export interface CampusBuildingCameraFocus {
  target: [number, number, number];
  position: [number, number, number];
}

interface BuildingAggregate {
  scope: BuildingScope;
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  floors: Set<string>;
  nodeIds: string[];
}

const DEFAULT_BASE_Y = -2.3;
const DEFAULT_MAX_BUILDINGS = 64;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "-");
}

export function normalizeFloorKey(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const normalized = normalizeKey(value);
  return normalized || null;
}

function parseFloorIndex(value: string | null | undefined): number | null {
  const normalized = normalizeFloorKey(value);
  if (!normalized) {
    return null;
  }

  const match = normalized.match(/-?\d+/);
  if (!match) {
    return null;
  }

  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) {
    return null;
  }

  if (parsed <= 0) {
    return 1;
  }

  return parsed;
}

function toBuildingLabel(value: string): string {
  const cleaned = value.trim();
  if (!cleaned) {
    return "Building";
  }

  if (/^[a-z0-9]{1,4}$/i.test(cleaned)) {
    return cleaned.toUpperCase();
  }

  return cleaned
    .split(/[-_]+/g)
    .filter(Boolean)
    .map((segment) => segment[0].toUpperCase() + segment.slice(1))
    .join(" ");
}

function toBuildingId(campusKey: string, buildingKey: string): string {
  return `${normalizeKey(campusKey)}:${normalizeKey(buildingKey)}`;
}

export function buildCampusBuildingId(campusKey: string, buildingKey: string): string {
  return toBuildingId(campusKey, buildingKey);
}

function toBuildingScope(spatialRefId: string | null | undefined): BuildingScope | null {
  const parsed = parseSpatialRefPath(spatialRefId);
  if (!parsed?.campus || !parsed.building) {
    return null;
  }

  const campusKey = normalizeKey(parsed.campus);
  const buildingKey = normalizeKey(parsed.building);

  return {
    id: toBuildingId(campusKey, buildingKey),
    campusKey,
    buildingKey,
    floorKey: parsed.floor ? normalizeKey(parsed.floor) : null,
  };
}

function hashUnit(seed: string, salt: number): number {
  let hash = 2166136261 ^ salt;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

function resolveBuildingGeometry(nodeCount: number, floors: number): CampusBuildingGeometryKind {
  if (nodeCount >= 10 || floors >= 4) {
    return "extrude";
  }
  return "box";
}

function rectangleFootprint(width: number, depth: number): Array<[number, number]> {
  const halfWidth = width / 2;
  const halfDepth = depth / 2;
  return [
    [-halfWidth, -halfDepth],
    [halfWidth, -halfDepth],
    [halfWidth, halfDepth],
    [-halfWidth, halfDepth],
  ];
}

function extrudedFootprint(seed: string, width: number, depth: number): Array<[number, number]> {
  const halfWidth = width / 2;
  const halfDepth = depth / 2;
  const limit = Math.max(0.8, Math.min(halfWidth, halfDepth) - 0.45);
  const cornerInset = clamp(0.9 + hashUnit(seed, 1) * Math.min(width, depth) * 0.18, 0.8, limit);
  const sideInset = clamp(0.8 + hashUnit(seed, 2) * Math.min(width, depth) * 0.16, 0.7, limit);

  return [
    [-halfWidth + sideInset, -halfDepth],
    [halfWidth - sideInset, -halfDepth],
    [halfWidth, -halfDepth + cornerInset],
    [halfWidth, halfDepth - cornerInset],
    [halfWidth - sideInset, halfDepth],
    [-halfWidth + sideInset, halfDepth],
    [-halfWidth, halfDepth - cornerInset],
    [-halfWidth, -halfDepth + cornerInset],
  ];
}

export function deriveBuildingIdFromSpatialRef(spatialRefId: string | null | undefined): string | null {
  return toBuildingScope(spatialRefId)?.id ?? null;
}

export function deriveSpatialBuildingScope(
  spatialRefId: string | null | undefined,
): SpatialBuildingScope {
  const scope = toBuildingScope(spatialRefId);
  if (!scope) {
    return {
      campusKey: null,
      buildingId: null,
      floorKey: null,
    };
  }

  return {
    campusKey: scope.campusKey,
    buildingId: scope.id,
    floorKey: scope.floorKey,
  };
}

export function isNodeVisibleInBuildingView(
  spatialRefId: string | null | undefined,
  viewState: CampusBuildingViewState | undefined,
): boolean {
  if (!viewState) {
    return true;
  }

  const scope = deriveSpatialBuildingScope(spatialRefId);
  const selectedBuildingId = viewState.selectedBuildingId ?? null;
  const selectedFloorKey = normalizeFloorKey(viewState.selectedFloorKey);

  if (viewState.visibleBuildingIds) {
    if (!scope.buildingId || !viewState.visibleBuildingIds.has(scope.buildingId)) {
      return false;
    }
  }

  if (viewState.hiddenBuildingIds && scope.buildingId && viewState.hiddenBuildingIds.has(scope.buildingId)) {
    return false;
  }

  const campusFilter = viewState.campusFilter?.trim();
  if (campusFilter) {
    const normalizedCampusFilter = normalizeKey(campusFilter);
    if (!scope.campusKey || scope.campusKey !== normalizedCampusFilter) {
      return false;
    }
  }

  if (viewState.floorFilterEnabled) {
    if (selectedBuildingId && scope.buildingId !== selectedBuildingId) {
      return false;
    }

    if (selectedFloorKey && scope.floorKey !== selectedFloorKey) {
      return false;
    }
  }

  return true;
}

export function resolveCampusBuildingCameraFocus(
  building: CampusBuilding,
  options: {
    floorKey?: string | null;
  } = {},
): CampusBuildingCameraFocus {
  const floorIndex = parseFloorIndex(options.floorKey);
  const perFloorHeight = 2.6;
  const floorY = floorIndex === null
    ? building.baseY + building.height * 0.45
    : building.baseY + Math.max(0.9, floorIndex * perFloorHeight - 1.2);

  const radius = Math.max(12, Math.max(building.width, building.depth) * 0.9 + 7.5);
  const cameraHeight = Math.min(22, floorY + Math.max(5, building.height * 0.9));

  return {
    target: [building.x, floorY, building.z],
    position: [building.x + radius, cameraHeight, building.z + radius],
  };
}

export function isCampusBuildingVisible(
  building: CampusBuilding,
  viewState: CampusBuildingViewState = {},
): boolean {
  if (viewState.visibleBuildingIds && !viewState.visibleBuildingIds.has(building.id)) {
    return false;
  }
  if (viewState.hiddenBuildingIds?.has(building.id)) {
    return false;
  }

  const campusFilter = viewState.campusFilter?.trim();
  if (campusFilter && building.campusKey !== normalizeKey(campusFilter)) {
    return false;
  }

  return true;
}

export function resolveCampusBuildingHighlight(
  building: CampusBuilding,
  viewState: CampusBuildingViewState = {},
): CampusBuildingHighlightState {
  const selected = viewState.selectedBuildingId ?? null;
  if (!selected) {
    return "default";
  }
  return selected === building.id ? "selected" : "muted";
}

export function buildBuildingByNodeIdIndex(
  buildings: readonly CampusBuilding[],
): Record<string, string> {
  const index: Record<string, string> = {};
  for (const building of buildings) {
    for (const nodeId of building.metadata.nodeIds) {
      index[nodeId] = building.id;
    }
  }
  return index;
}

export function deriveCampusBuildings(
  nodes: readonly TwinNode[],
  options: DeriveCampusBuildingsOptions = {},
): CampusBuilding[] {
  const aggregateByBuildingId = new Map<string, BuildingAggregate>();

  for (const node of nodes) {
    const scope = toBuildingScope(node.spatialRefId);
    if (!scope) {
      continue;
    }

    const aggregate =
      aggregateByBuildingId.get(scope.id) ??
      {
        scope,
        minX: Number.POSITIVE_INFINITY,
        maxX: Number.NEGATIVE_INFINITY,
        minZ: Number.POSITIVE_INFINITY,
        maxZ: Number.NEGATIVE_INFINITY,
        floors: new Set<string>(),
        nodeIds: [],
      };

    aggregate.minX = Math.min(aggregate.minX, node.x);
    aggregate.maxX = Math.max(aggregate.maxX, node.x);
    aggregate.minZ = Math.min(aggregate.minZ, node.z);
    aggregate.maxZ = Math.max(aggregate.maxZ, node.z);
    aggregate.nodeIds.push(node.id);
    if (scope.floorKey) {
      aggregate.floors.add(scope.floorKey);
    }

    aggregateByBuildingId.set(scope.id, aggregate);
  }

  const maxBuildings = Math.max(0, options.maxBuildings ?? DEFAULT_MAX_BUILDINGS);
  const baseY = options.baseY ?? DEFAULT_BASE_Y;

  return [...aggregateByBuildingId.values()]
    .sort((left, right) => left.scope.id.localeCompare(right.scope.id))
    .slice(0, maxBuildings)
    .map((aggregate) => {
      const nodeCount = aggregate.nodeIds.length;
      const spreadX = Math.max(0, aggregate.maxX - aggregate.minX);
      const spreadZ = Math.max(0, aggregate.maxZ - aggregate.minZ);
      const spreadPadding = 4.8 + Math.min(6, Math.sqrt(nodeCount) * 1.35);
      const width = clamp(spreadX + spreadPadding, 6, 42);
      const depth = clamp(spreadZ + spreadPadding, 6, 42);

      const floors = Math.max(1, aggregate.floors.size);
      const geometry = resolveBuildingGeometry(nodeCount, floors);
      const height = clamp(floors * 1.45 + 2.2, 3.4, 14.5);
      const footprint =
        geometry === "box"
          ? rectangleFootprint(width, depth)
          : extrudedFootprint(aggregate.scope.id, width, depth);

      return {
        id: aggregate.scope.id,
        campusKey: aggregate.scope.campusKey,
        buildingKey: aggregate.scope.buildingKey,
        label: toBuildingLabel(aggregate.scope.buildingKey),
        geometry,
        x: (aggregate.minX + aggregate.maxX) / 2,
        z: (aggregate.minZ + aggregate.maxZ) / 2,
        baseY,
        width,
        depth,
        height,
        floors,
        nodeCount,
        metadata: {
          floorKeys: [...aggregate.floors].sort((left, right) => left.localeCompare(right)),
          nodeIds: [...aggregate.nodeIds].sort((left, right) => left.localeCompare(right)),
        },
        footprint,
      } satisfies CampusBuilding;
    });
}

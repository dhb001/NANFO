import type { CongestionSeverity, TwinNode } from "@/features/digitalTwin/sceneAdapter";
import { normalizeDeviceType } from "@/features/digitalTwin/deviceVisuals";
import {
  deriveSpatialBuildingScope,
  type CampusBuilding,
} from "@/features/digitalTwin/campusBuildings";

export const WIRELESS_COVERAGE_POLICY_VERSION = "rf.material_attenuation.v1";

const DEFAULT_MAX_COVERAGE_CELLS = 180;
const DEFAULT_TRANSMIT_POWER_DBM = 20;

export interface WirelessCoverageCell {
  id: string;
  sourceNodeId: string;
  spatialRefId: string | null;
  x: number;
  y: number;
  z: number;
  radius: number;
  intensity: number;
  severity: CongestionSeverity;
  wallMaterial: string | null;
  attenuationDb: number | null;
  solverMode: "rf_material_baseline";
  syntheticEstimate: true;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function isWirelessAccessPointType(deviceType: string): boolean {
  const normalized = normalizeDeviceType(deviceType);
  return (
    normalized === "wireless_ap" ||
    normalized === "ap" ||
    normalized.endsWith("_ap") ||
    normalized.includes("access_point") ||
    normalized.includes("wireless")
  );
}

function normalizeWallMaterial(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_");
  return normalized || null;
}

function defaultAttenuationForMaterial(material: string | null): number {
  if (material === "concrete") {
    return 14;
  }
  if (material === "brick") {
    return 10;
  }
  if (material === "glass") {
    return 4;
  }
  if (material === "drywall") {
    return 6;
  }
  if (material === "metal") {
    return 18;
  }
  return 7;
}

function basePathLossBySeverity(severity: CongestionSeverity): number {
  if (severity === "low") {
    return 8;
  }
  if (severity === "medium") {
    return 11;
  }
  if (severity === "high") {
    return 14;
  }
  return 10;
}

function computeRfBaseline(
  severity: CongestionSeverity,
  score: number | null,
  attenuationDb: number,
): {
  radius: number;
  intensity: number;
} {
  const congestionPenalty = score === null ? 0.5 : clamp(score, 0, 1) * 4;
  const pathLoss = basePathLossBySeverity(severity) + attenuationDb * 0.42 + congestionPenalty;
  const signalBudget = DEFAULT_TRANSMIT_POWER_DBM - pathLoss;

  const radius = clamp(9.8 + signalBudget * 0.35, 2.8, 11.4);
  const intensity = clamp((signalBudget + 10) / 18, 0.18, 0.94);

  return {
    radius,
    intensity,
  };
}

function buildingById(buildings: readonly CampusBuilding[]): Record<string, CampusBuilding> {
  return buildings.reduce<Record<string, CampusBuilding>>((acc, building) => {
    acc[building.id] = building;
    return acc;
  }, {});
}

export function deriveWirelessCoverageCells(
  nodes: readonly TwinNode[],
  options: {
    maxCells?: number;
    campusBuildings?: readonly CampusBuilding[];
  } = {},
): WirelessCoverageCell[] {
  const maxCells = Math.max(0, options.maxCells ?? DEFAULT_MAX_COVERAGE_CELLS);
  const indexedBuildings = buildingById(options.campusBuildings ?? []);

  return [...nodes]
    .filter((node) => isWirelessAccessPointType(node.type))
    .sort((left, right) => left.id.localeCompare(right.id))
    .slice(0, maxCells)
    .map((node) => {
      const buildingScope = deriveSpatialBuildingScope(node.spatialRefId);
      const building = buildingScope.buildingId ? indexedBuildings[buildingScope.buildingId] : undefined;
      const wallMaterial = normalizeWallMaterial(building?.metadata.wallMaterial ?? null);
      const attenuationDb =
        typeof building?.metadata.attenuationDb === "number" && Number.isFinite(building.metadata.attenuationDb)
          ? clamp(building.metadata.attenuationDb, 0, 80)
          : defaultAttenuationForMaterial(wallMaterial);

      const rf = computeRfBaseline(node.congestion.severity, node.congestion.score, attenuationDb);
      return {
        id: `coverage:${node.id}`,
        sourceNodeId: node.id,
        spatialRefId: node.spatialRefId,
        x: node.x,
        y: node.y + 0.04,
        z: node.z,
        radius: rf.radius,
        intensity: rf.intensity,
        severity: node.congestion.severity,
        wallMaterial,
        attenuationDb,
        solverMode: "rf_material_baseline",
        syntheticEstimate: true,
      } satisfies WirelessCoverageCell;
    });
}

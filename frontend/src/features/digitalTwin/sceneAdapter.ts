import { TopologyEdge, TopologyNode } from "@/shared/types/network";
import { DigitalTwinDeltaData, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";

export type CongestionSeverity = "low" | "medium" | "high" | "neutral";

export const CONGESTION_THRESHOLDS = {
  lowUpperExclusive: 0.4,
  mediumUpperExclusive: 0.75,
  latencyReferenceMs: 120,
} as const;

export interface TwinMetricSnapshot {
  metric: string;
  value: number;
  unit: string | null;
  observedAt: string;
  source: string;
  normalizedScore: number;
}

export interface TwinCongestion {
  severity: CongestionSeverity;
  score: number | null;
  metrics: TwinMetricSnapshot[];
}

export interface TwinNode {
  id: string;
  hostname: string;
  type: string;
  status: string;
  x: number;
  y: number;
  z: number;
  spatialRefId: string | null;
  congestion: TwinCongestion;
}

export interface TwinLink {
  id: string;
  source: [number, number, number];
  target: [number, number, number];
  sourceId: string;
  targetId: string;
  edgeType: string;
}

export interface TwinOverlayObject {
  id: string;
  objectType: string;
  status: string | null;
  state: string | null;
  simulationId: string | null;
  intentId: string | null;
  spatialRefId: string | null;
  x: number;
  y: number;
  z: number;
}

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

interface CanonicalTwinNode {
  device_id: string;
  hostname?: string;
  device_type?: string;
  status?: string;
  spatial_ref_id?: string | null;
}

interface SceneAdapterInput {
  baseNodes: TopologyNode[];
  baseEdges: TopologyEdge[];
  liveNodesByDeviceId: Record<string, TopologyDeltaData["node"]>;
  telemetryByDeviceMetric: Record<string, TelemetryDeltaData["metric"]>;
  sceneObjects: Record<string, DigitalTwinDeltaData["scene_object"]>;
  sceneObjectIdsNewestFirst: string[];
  importedSpatialRefByDeviceId?: Record<string, string>;
}

export interface TwinSceneModel {
  nodes: TwinNode[];
  links: TwinLink[];
  overlays: TwinOverlayObject[];
  nodeById: Record<string, TwinNode>;
}

function hashPosition(seed: string, axis: number) {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash << 5) - hash + seed.charCodeAt(i) + axis * 17;
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

export function parseSpatialRefPath(spatialRefId: string | null | undefined): SpatialRefPath | null {
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

export function deriveDeterministicPlacement(spatialRefId: string | null | undefined, fallbackSeed: string) {
  const parsedPath = parseSpatialRefPath(spatialRefId);
  if (!parsedPath) {
    return {
      x: hashPosition(fallbackSeed, 1),
      y: hashPosition(fallbackSeed, 2) * 0.22,
      z: hashPosition(fallbackSeed, 3),
      mode: "hash_fallback" as const,
      parsedPath: null,
    };
  }

  const extras = parsedPath.segments.slice(5).join("/");
  const floorIndex = parseFloorIndex(parsedPath.floor);
  const floorY = floorIndex !== null ? floorIndex * 2.6 - 2.6 : hashRange(`floor:${parsedPath.normalized}`, -1.6, 4.8);

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
    mode: "spatial_ref" as const,
    parsedPath,
  };
}

function mergeCanonicalNodes(baseNodes: TopologyNode[], liveNodes: CanonicalTwinNode[]): CanonicalTwinNode[] {
  const merged = new Map<string, CanonicalTwinNode>();

  for (const node of baseNodes) {
    merged.set(node.device_id, node);
  }

  for (const node of liveNodes) {
    const previous = merged.get(node.device_id);
    merged.set(node.device_id, {
      ...(previous ?? {}),
      ...node,
    });
  }

  return [...merged.values()].sort((left, right) => left.device_id.localeCompare(right.device_id));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function normalizeMetricName(metric: string) {
  return metric.trim().toLowerCase();
}

function toCongestionMetricScore(metric: TelemetryDeltaData["metric"]): TwinMetricSnapshot | null {
  if (!isFiniteNumber(metric.value)) {
    return null;
  }

  const metricName = normalizeMetricName(metric.metric);
  const unit = (metric.unit ?? "").trim().toLowerCase();

  const isPercentCongestionMetric =
    unit === "%" &&
    (metricName.includes("utilization") ||
      metricName.includes("cpu") ||
      metricName.includes("bandwidth") ||
      metricName.includes("loss"));

  const isLatencyCongestionMetric = unit === "ms" && metricName.includes("latency");

  if (!isPercentCongestionMetric && !isLatencyCongestionMetric) {
    return null;
  }

  const normalizedScore = isPercentCongestionMetric
    ? Math.max(0, Math.min(1, metric.value / 100))
    : Math.max(0, Math.min(1, metric.value / CONGESTION_THRESHOLDS.latencyReferenceMs));

  return {
    metric: metric.metric,
    value: metric.value,
    unit: metric.unit,
    observedAt: metric.observed_at,
    source: metric.source,
    normalizedScore,
  };
}

export function mapCongestionSeverity(score: number | null): CongestionSeverity {
  if (score === null) {
    return "neutral";
  }
  if (score < CONGESTION_THRESHOLDS.lowUpperExclusive) {
    return "low";
  }
  if (score < CONGESTION_THRESHOLDS.mediumUpperExclusive) {
    return "medium";
  }
  return "high";
}

export function deriveDeviceCongestion(metrics: TelemetryDeltaData["metric"][]): TwinCongestion {
  const candidates = metrics
    .map(toCongestionMetricScore)
    .filter((item): item is TwinMetricSnapshot => item !== null)
    .sort((left, right) => {
      const leftTs = Date.parse(left.observedAt);
      const rightTs = Date.parse(right.observedAt);
      if (Number.isNaN(leftTs) && Number.isNaN(rightTs)) {
        return left.metric.localeCompare(right.metric);
      }
      if (Number.isNaN(leftTs)) {
        return 1;
      }
      if (Number.isNaN(rightTs)) {
        return -1;
      }
      return rightTs - leftTs;
    });

  if (candidates.length === 0) {
    return {
      severity: "neutral",
      score: null,
      metrics: [],
    };
  }

  const score = candidates.reduce((maxScore, item) => Math.max(maxScore, item.normalizedScore), 0);
  return {
    severity: mapCongestionSeverity(score),
    score,
    metrics: candidates.slice(0, 6),
  };
}

function getSceneObjectSpatialRef(sceneObject: DigitalTwinDeltaData["scene_object"]): string | null {
  if (sceneObject.spatial_ref_id) {
    return sceneObject.spatial_ref_id;
  }

  if (!sceneObject.changed_fields || typeof sceneObject.changed_fields !== "object") {
    return null;
  }

  const spatialRefCandidate = (sceneObject.changed_fields as Record<string, unknown>).spatial_ref_id;
  if (typeof spatialRefCandidate === "string" && spatialRefCandidate.trim()) {
    return spatialRefCandidate;
  }

  return null;
}

export function buildTwinSceneModel(input: SceneAdapterInput): TwinSceneModel {
  const mergedNodes = mergeCanonicalNodes(input.baseNodes, Object.values(input.liveNodesByDeviceId));

  const telemetryByDeviceId = Object.values(input.telemetryByDeviceMetric).reduce<Record<string, TelemetryDeltaData["metric"][]>>(
    (acc, metric) => {
      const bucket = acc[metric.device_id] ?? [];
      bucket.push(metric);
      acc[metric.device_id] = bucket;
      return acc;
    },
    {},
  );

  const nodes = mergedNodes.map((node) => {
    const id = node.device_id;
    const importedSpatialRef = input.importedSpatialRefByDeviceId?.[id] ?? null;
    const spatialRefId = node.spatial_ref_id ?? importedSpatialRef;
    const placement = deriveDeterministicPlacement(spatialRefId, id);
    const congestion = deriveDeviceCongestion(telemetryByDeviceId[id] ?? []);

    return {
      id,
      hostname: node.hostname ?? id.slice(0, 8),
      type: node.device_type ?? "device",
      status: node.status ?? "unknown",
      x: placement.x,
      y: placement.y,
      z: placement.z,
      spatialRefId: spatialRefId ?? null,
      congestion,
    } satisfies TwinNode;
  });

  const nodeByIdMap = new Map(nodes.map((node) => [node.id, node]));

  const links = [...input.baseEdges]
    .sort((left, right) => {
      const leftKey = `${left.source_id}:${left.target_id}:${left.edge_type}`;
      const rightKey = `${right.source_id}:${right.target_id}:${right.edge_type}`;
      return leftKey.localeCompare(rightKey);
    })
    .reduce<TwinLink[]>((acc, edge) => {
      const sourceNode = nodeByIdMap.get(edge.source_id);
      const targetNode = nodeByIdMap.get(edge.target_id);
      if (!sourceNode || !targetNode) {
        return acc;
      }

      acc.push({
        id: `${edge.source_id}:${edge.target_id}:${edge.edge_type}`,
        source: [sourceNode.x, sourceNode.y, sourceNode.z],
        target: [targetNode.x, targetNode.y, targetNode.z],
        sourceId: sourceNode.id,
        targetId: targetNode.id,
        edgeType: edge.edge_type,
      });
      return acc;
    }, []);

  const seenOverlayIds = new Set<string>();
  const orderedOverlayIds = input.sceneObjectIdsNewestFirst.length > 0
    ? input.sceneObjectIdsNewestFirst
    : Object.keys(input.sceneObjects).sort();

  const overlays: TwinOverlayObject[] = [];
  for (const overlayId of orderedOverlayIds) {
    if (seenOverlayIds.has(overlayId)) {
      continue;
    }
    seenOverlayIds.add(overlayId);

    const sceneObject = input.sceneObjects[overlayId];
    if (!sceneObject) {
      continue;
    }

    const spatialRefId = getSceneObjectSpatialRef(sceneObject);
    const placement = deriveDeterministicPlacement(spatialRefId, sceneObject.id);
    overlays.push({
      id: sceneObject.id,
      objectType: sceneObject.object_type,
      status: typeof sceneObject.status === "string" ? sceneObject.status : null,
      state: typeof sceneObject.state === "string" ? sceneObject.state : null,
      simulationId: typeof sceneObject.simulation_id === "string" ? sceneObject.simulation_id : null,
      intentId: typeof sceneObject.intent_id === "string" ? sceneObject.intent_id : null,
      spatialRefId,
      x: placement.x,
      y: placement.y + 0.9,
      z: placement.z,
    });
  }

  const nodeById = nodes.reduce<Record<string, TwinNode>>((acc, node) => {
    acc[node.id] = node;
    return acc;
  }, {});

  return {
    nodes,
    links,
    overlays,
    nodeById,
  };
}

import { TopologyEdge, TopologyNode } from "@/shared/types/network";
import { DigitalTwinDeltaData, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";
import {
  deriveDeterministicPlacement as derivePlacementWithProvider,
  parseSpatialRefPath as parseSpatialRefPathWithProvider,
  type SpatialRefPath,
} from "@/features/digitalTwin/spatialProjection";

export type CongestionSeverity = "low" | "medium" | "high" | "neutral";

export const CONGESTION_THRESHOLDS = {
  lowUpperExclusive: 0.4,
  mediumUpperExclusive: 0.75,
  latencyReferenceMs: 120,
} as const;

export const CONGESTION_POLICY_VERSION = "v2.0.0";

interface CongestionPolicyRule {
  id: string;
  label: string;
  priority: number;
  unit: "%" | "ms";
  metricIncludes: string[];
  lowUpperExclusive: number;
  mediumUpperExclusive: number;
  normalizeReference: number;
}

export const CONGESTION_POLICY_RULES: readonly CongestionPolicyRule[] = [
  {
    id: "packet_loss_percent",
    label: "Packet loss",
    priority: 400,
    unit: "%",
    metricIncludes: ["packet_loss", "loss"],
    lowUpperExclusive: 1,
    mediumUpperExclusive: 3,
    normalizeReference: 10,
  },
  {
    id: "latency_ms",
    label: "Latency",
    priority: 300,
    unit: "ms",
    metricIncludes: ["latency", "rtt"],
    lowUpperExclusive: 40,
    mediumUpperExclusive: 90,
    normalizeReference: 140,
  },
  {
    id: "link_utilization_percent",
    label: "Link utilization",
    priority: 200,
    unit: "%",
    metricIncludes: ["utilization", "bandwidth", "throughput"],
    lowUpperExclusive: 40,
    mediumUpperExclusive: 75,
    normalizeReference: 100,
  },
  {
    id: "cpu_utilization_percent",
    label: "CPU utilization",
    priority: 100,
    unit: "%",
    metricIncludes: ["cpu"],
    lowUpperExclusive: 40,
    mediumUpperExclusive: 75,
    normalizeReference: 100,
  },
] as const;

const MAX_CONGESTION_METRICS_PER_DEVICE = 12;
const MAX_CONGESTION_KEYS = 240;

export interface TwinMetricSnapshot {
  metric: string;
  value: number;
  unit: string | null;
  observedAt: string;
  source: string;
  normalizedScore: number;
  severity: Exclude<CongestionSeverity, "neutral">;
  policyId: string;
  policyPriority: number;
  lowUpperExclusive: number;
  mediumUpperExclusive: number;
}

export interface TwinCongestion {
  severity: CongestionSeverity;
  score: number | null;
  metrics: TwinMetricSnapshot[];
  policyVersion: string;
  primaryPolicyId: string | null;
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
  telemetryKeysNewestFirst: string[];
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

export function parseSpatialRefPath(spatialRefId: string | null | undefined): SpatialRefPath | null {
  return parseSpatialRefPathWithProvider(spatialRefId);
}

export function deriveDeterministicPlacement(spatialRefId: string | null | undefined, fallbackSeed: string) {
  return derivePlacementWithProvider(spatialRefId, fallbackSeed);
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

function toCongestionPolicyHint(tags: Record<string, unknown> | undefined): string | null {
  if (!tags || typeof tags !== "object") {
    return null;
  }

  const hint = tags.congestion_policy;
  if (typeof hint !== "string") {
    return null;
  }

  const normalized = hint.trim().toLowerCase();
  return normalized || null;
}

function resolveCongestionPolicyRule(metric: TelemetryDeltaData["metric"]): CongestionPolicyRule | null {
  const unit = (metric.unit ?? "").trim().toLowerCase();
  const metricName = normalizeMetricName(metric.metric);
  const policyHint = toCongestionPolicyHint(metric.tags);

  if (policyHint) {
    const hintedRule = CONGESTION_POLICY_RULES.find((rule) => rule.id === policyHint);
    if (hintedRule && hintedRule.unit === unit) {
      return hintedRule;
    }
  }

  return (
    CONGESTION_POLICY_RULES.find((rule) => {
      if (rule.unit !== unit) {
        return false;
      }
      return rule.metricIncludes.some((needle) => metricName.includes(needle));
    }) ?? null
  );
}

function mapCongestionSeverityForRule(value: number, rule: CongestionPolicyRule): Exclude<CongestionSeverity, "neutral"> {
  if (value < rule.lowUpperExclusive) {
    return "low";
  }
  if (value < rule.mediumUpperExclusive) {
    return "medium";
  }
  return "high";
}

function congestionSeverityRank(severity: CongestionSeverity): number {
  if (severity === "high") {
    return 3;
  }
  if (severity === "medium") {
    return 2;
  }
  if (severity === "low") {
    return 1;
  }
  return 0;
}

function toCongestionMetricScore(metric: TelemetryDeltaData["metric"]): TwinMetricSnapshot | null {
  if (!isFiniteNumber(metric.value)) {
    return null;
  }

  const policyRule = resolveCongestionPolicyRule(metric);
  if (!policyRule) {
    return null;
  }

  const normalizedScore = Math.max(0, Math.min(1, metric.value / policyRule.normalizeReference));
  const severity = mapCongestionSeverityForRule(metric.value, policyRule);

  return {
    metric: metric.metric,
    value: metric.value,
    unit: metric.unit,
    observedAt: metric.observed_at,
    source: metric.source,
    normalizedScore,
    severity,
    policyId: policyRule.id,
    policyPriority: policyRule.priority,
    lowUpperExclusive: policyRule.lowUpperExclusive,
    mediumUpperExclusive: policyRule.mediumUpperExclusive,
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
      const severityDelta = congestionSeverityRank(right.severity) - congestionSeverityRank(left.severity);
      if (severityDelta !== 0) {
        return severityDelta;
      }

      const policyDelta = right.policyPriority - left.policyPriority;
      if (policyDelta !== 0) {
        return policyDelta;
      }

      const leftTs = Date.parse(left.observedAt);
      const rightTs = Date.parse(right.observedAt);
      if (Number.isNaN(leftTs) && Number.isNaN(rightTs)) {
        const metricDelta = left.metric.localeCompare(right.metric);
        if (metricDelta !== 0) {
          return metricDelta;
        }
        return left.policyId.localeCompare(right.policyId);
      }
      if (Number.isNaN(leftTs)) {
        return 1;
      }
      if (Number.isNaN(rightTs)) {
        return -1;
      }
      if (rightTs !== leftTs) {
        return rightTs - leftTs;
      }

      const metricDelta = left.metric.localeCompare(right.metric);
      if (metricDelta !== 0) {
        return metricDelta;
      }

      return left.policyId.localeCompare(right.policyId);
    });

  if (candidates.length === 0) {
    return {
      severity: "neutral",
      score: null,
      metrics: [],
      policyVersion: CONGESTION_POLICY_VERSION,
      primaryPolicyId: null,
    };
  }

  const primary = candidates[0];
  return {
    severity: primary.severity,
    score: primary.normalizedScore,
    metrics: candidates.slice(0, 6),
    policyVersion: CONGESTION_POLICY_VERSION,
    primaryPolicyId: primary.policyId,
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

  const telemetryByDeviceId = (
    input.telemetryKeysNewestFirst.length > 0
      ? input.telemetryKeysNewestFirst
      : Object.keys(input.telemetryByDeviceMetric).sort()
  )
    .slice(0, MAX_CONGESTION_KEYS)
    .reduce<Record<string, TelemetryDeltaData["metric"][]>>((acc, telemetryKey) => {
      const metric = input.telemetryByDeviceMetric[telemetryKey];
      if (!metric) {
        return acc;
      }

      const bucket = acc[metric.device_id] ?? [];
      if (bucket.length >= MAX_CONGESTION_METRICS_PER_DEVICE) {
        return acc;
      }

      bucket.push(metric);
      acc[metric.device_id] = bucket;
      return acc;
    }, {});

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

  overlays.sort((left, right) => {
    const leftPriority = left.objectType === "simulation_state" ? 0 : left.objectType === "intent_state" ? 1 : 2;
    const rightPriority = right.objectType === "simulation_state" ? 0 : right.objectType === "intent_state" ? 1 : 2;
    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }

    return left.id.localeCompare(right.id);
  });

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

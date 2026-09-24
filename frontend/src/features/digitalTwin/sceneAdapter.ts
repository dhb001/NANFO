import { TopologyEdge, TopologyNode } from "@/shared/types/network";
import { topologyEdgeIdentity } from "@/features/topology/edgeIdentity";
import { DigitalTwinDeltaData, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";
import {
  deriveDeterministicPlacement as derivePlacementWithProvider,
  parseSpatialRefPath as parseSpatialRefPathWithProvider,
  type SpatialRefPath,
} from "@/features/digitalTwin/spatialProjection";
import {
  HEURISTIC_LEVEL_SEVERITY,
  VISUAL_HEURISTIC_ID,
  visualHeuristicLevel,
  type DetectorRuleMirror,
  type HeuristicLevel,
} from "@/features/digitalTwin/twinSeverity";

/** Visual-heuristic colour class only. Backend alerts are the authoritative severity. */
export type CongestionSeverity = "low" | "medium" | "high" | "neutral";

/** Display freshness window for live samples (not the backend detector window). */
export const TWIN_METRIC_MAX_AGE_MS = 60_000;

export interface TwinMetricSnapshot {
  stale?: boolean;
  tags: Record<string, unknown>;
  metric: string;
  value: number;
  unit: string | null;
  observedAt: string;
  source: string;
  /** Mirrors the backend detector default thresholds for this exact metric/unit. */
  level: HeuristicLevel;
  severity: Exclude<CongestionSeverity, "neutral">;
  rule: DetectorRuleMirror;
}

export interface TwinCongestion {
  /** Visual heuristic only; never an alert, never a policy. */
  severity: CongestionSeverity;
  metrics: TwinMetricSnapshot[];
  heuristic: typeof VISUAL_HEURISTIC_ID;
  primaryMetric: string | null;
}

/** Topology and placement only: never changes when telemetry changes. */
export interface TwinNode {
  rotation?: [number, number, number];
  placementSource?: "canonical" | "schematic";
  spatialObjectId?: string;
  id: string;
  hostname: string;
  type: string;
  status: string;
  x: number;
  y: number;
  z: number;
  /** Effective reference: a session-only sidecar mapping overrides the persisted value. */
  spatialRefId: string | null;
  /** Backend `spatial_ref_id` only. Persisted actions must use this, never session mappings. */
  persistedSpatialRefId?: string | null;
}

export interface TwinSceneNode extends TwinNode {
  congestion: TwinCongestion;
}

export interface TwinLink {
  id: string;
  source: [number, number, number];
  target: [number, number, number];
  sourceId: string;
  targetId: string;
  edgeType: string;
  metadata: TopologyEdge["metadata"];
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

export interface TwinTopologyInput {
  topologyTombstones?: Record<string, number>;
  baseNodes: TopologyNode[];
  baseEdges: TopologyEdge[];
  liveNodesByDeviceId: Record<string, TopologyDeltaData["node"]>;
  importedSpatialRefByDeviceId?: Record<string, string>;
}

export interface TwinTopology<N extends TwinNode = TwinNode> {
  nodes: N[];
  links: TwinLink[];
  nodeById: Record<string, N>;
}

export interface SceneAdapterInput extends TwinTopologyInput {
  now?: number;
  telemetryByDeviceMetric: Record<string, TelemetryDeltaData["metric"]>;
  telemetryKeysNewestFirst: string[];
  sceneObjects: Record<string, DigitalTwinDeltaData["scene_object"]>;
  sceneObjectIdsNewestFirst: string[];
}

export interface TwinSceneModel extends TwinTopology<TwinSceneNode> {
  overlays: TwinOverlayObject[];
}

export const NEUTRAL_CONGESTION: TwinCongestion = Object.freeze({
  severity: "neutral",
  metrics: Object.freeze([]) as unknown as TwinMetricSnapshot[],
  heuristic: VISUAL_HEURISTIC_ID,
  primaryMetric: null,
}) as TwinCongestion;

export function parseSpatialRefPath(spatialRefId: string | null | undefined): SpatialRefPath | null {
  return parseSpatialRefPathWithProvider(spatialRefId);
}

export function deriveDeterministicPlacement(spatialRefId: string | null | undefined, fallbackSeed: string) {
  return derivePlacementWithProvider(spatialRefId, fallbackSeed);
}

function mergeCanonicalNodes(baseNodes: TopologyNode[], liveNodes: CanonicalTwinNode[]): CanonicalTwinNode[] {
  const merged = new Map<string, CanonicalTwinNode>();
  for (const node of baseNodes) merged.set(node.device_id, node);
  for (const node of liveNodes) merged.set(node.device_id, { ...(merged.get(node.device_id) ?? {}), ...node });
  return [...merged.values()].sort((left, right) => left.device_id.localeCompare(right.device_id));
}

const SEVERITY_RANK: Readonly<Record<CongestionSeverity, number>> = { high: 3, medium: 2, low: 1, neutral: 0 };

function toMetricSnapshot(metric: TelemetryDeltaData["metric"], now: number): TwinMetricSnapshot | null {
  if (typeof metric.value !== "number" || !Number.isFinite(metric.value)) return null;
  const heuristic = visualHeuristicLevel(metric.metric, metric.unit, metric.value);
  if (!heuristic) return null;
  const observed = Date.parse(metric.observed_at);
  const stale = metric.tags?.stale === true || !Number.isFinite(observed) || now - observed > TWIN_METRIC_MAX_AGE_MS || observed > now;
  return {
    metric: metric.metric,
    value: metric.value,
    unit: metric.unit,
    observedAt: metric.observed_at,
    tags: metric.tags,
    source: metric.source,
    level: heuristic.level,
    severity: HEURISTIC_LEVEL_SEVERITY[heuristic.level],
    rule: heuristic.rule,
    stale,
  };
}

/** Visual heuristic over the latest samples of one device. Stale samples never colour a node. */
export function deriveDeviceCongestion(metrics: readonly TelemetryDeltaData["metric"][], now = Date.now()): TwinCongestion {
  const candidates = metrics
    .map((metric) => toMetricSnapshot(metric, now))
    .filter((item): item is TwinMetricSnapshot => item !== null)
    .sort((left, right) => {
      if (left.stale !== right.stale) return left.stale ? 1 : -1;
      const severityDelta = SEVERITY_RANK[right.severity] - SEVERITY_RANK[left.severity];
      if (severityDelta !== 0) return severityDelta;
      const leftTs = Date.parse(left.observedAt);
      const rightTs = Date.parse(right.observedAt);
      if (Number.isFinite(leftTs) && Number.isFinite(rightTs) && leftTs !== rightTs) return rightTs - leftTs;
      if (Number.isFinite(leftTs) !== Number.isFinite(rightTs)) return Number.isFinite(leftTs) ? -1 : 1;
      return left.metric.localeCompare(right.metric) || left.source.localeCompare(right.source);
    });
  if (candidates.length === 0) return NEUTRAL_CONGESTION;
  const primary = candidates[0];
  return {
    severity: primary.stale ? "neutral" : primary.severity,
    metrics: candidates.slice(0, 6),
    heuristic: VISUAL_HEURISTIC_ID,
    primaryMetric: primary.stale ? null : primary.metric,
  };
}

/**
 * Latest telemetry grouped per device. The realtime store bounds resources/series
 * separately from flow history; a second truncation here would starve valid series.
 */
export function groupTelemetryByDevice(
  telemetryByDeviceMetric: Record<string, TelemetryDeltaData["metric"]>,
  telemetryKeysNewestFirst: readonly string[],
): Record<string, TelemetryDeltaData["metric"][]> {
  const keys = telemetryKeysNewestFirst.length > 0 ? telemetryKeysNewestFirst : Object.keys(telemetryByDeviceMetric).sort();
  const grouped: Record<string, TelemetryDeltaData["metric"][]> = {};
  for (const key of keys) {
    const metric = telemetryByDeviceMetric[key];
    if (!metric || metric.metric.startsWith("flow_")) continue;
    (grouped[metric.device_id] ??= []).push(metric);
  }
  return grouped;
}

export function deriveCongestionByDevice(
  telemetryByDeviceMetric: Record<string, TelemetryDeltaData["metric"]>,
  telemetryKeysNewestFirst: readonly string[],
  now = Date.now(),
): Record<string, TwinCongestion> {
  const grouped = groupTelemetryByDevice(telemetryByDeviceMetric, telemetryKeysNewestFirst);
  const result: Record<string, TwinCongestion> = {};
  for (const [deviceId, metrics] of Object.entries(grouped)) {
    const congestion = deriveDeviceCongestion(metrics, now);
    if (congestion !== NEUTRAL_CONGESTION) result[deviceId] = congestion;
  }
  return result;
}

// Edge identities are canonical JSON strings: compute them once per edge array, never
// inside a sort comparator, and reuse them for every topology rebuild of the same graph.
const edgeOrderCache = new WeakMap<readonly TopologyEdge[], Array<{ id: string; edge: TopologyEdge }>>();

export function orderedEdgeIdentities(edges: readonly TopologyEdge[]): Array<{ id: string; edge: TopologyEdge }> {
  const cached = edgeOrderCache.get(edges);
  if (cached) return cached;
  const seen = new Set<string>();
  const ordered = edges
    .map((edge) => ({ id: topologyEdgeIdentity(edge), edge }))
    .sort((left, right) => (left.id < right.id ? -1 : left.id > right.id ? 1 : 0))
    .filter((item) => (seen.has(item.id) ? false : (seen.add(item.id), true)));
  edgeOrderCache.set(edges, ordered);
  return ordered;
}

function cleanRef(value: string | null | undefined): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function buildTwinTopology(input: TwinTopologyInput): TwinTopology {
  const tombstones = input.topologyTombstones ?? {};
  const nodes: TwinNode[] = mergeCanonicalNodes(input.baseNodes, Object.values(input.liveNodesByDeviceId))
    .filter((node) => !Object.hasOwn(tombstones, node.device_id))
    .map((node) => {
      const id = node.device_id;
      const persistedSpatialRefId = cleanRef(node.spatial_ref_id);
      const spatialRefId = input.importedSpatialRefByDeviceId?.[id] ?? persistedSpatialRefId;
      const placement = deriveDeterministicPlacement(spatialRefId, id);
      return {
        id,
        hostname: node.hostname ?? id.slice(0, 8),
        type: node.device_type ?? "device",
        status: node.status ?? "unknown",
        x: placement.x,
        y: placement.y,
        z: placement.z,
        spatialRefId: spatialRefId ?? null,
        persistedSpatialRefId,
      } satisfies TwinNode;
    });
  const nodeById: Record<string, TwinNode> = {};
  for (const node of nodes) nodeById[node.id] = node;
  const links: TwinLink[] = [];
  for (const { id, edge } of orderedEdgeIdentities(input.baseEdges)) {
    const sourceNode = nodeById[edge.source_id];
    const targetNode = nodeById[edge.target_id];
    if (!sourceNode || !targetNode) continue;
    links.push({
      id,
      source: [sourceNode.x, sourceNode.y, sourceNode.z],
      target: [targetNode.x, targetNode.y, targetNode.z],
      sourceId: sourceNode.id,
      targetId: targetNode.id,
      edgeType: edge.edge_type,
      metadata: edge.metadata,
    });
  }
  return { nodes, links, nodeById };
}

function getSceneObjectSpatialRef(sceneObject: DigitalTwinDeltaData["scene_object"]): string | null {
  if (sceneObject.spatial_ref_id) return sceneObject.spatial_ref_id;
  if (!sceneObject.changed_fields || typeof sceneObject.changed_fields !== "object") return null;
  const candidate = (sceneObject.changed_fields as Record<string, unknown>).spatial_ref_id;
  return typeof candidate === "string" && candidate.trim() ? candidate : null;
}

const OVERLAY_TYPE_PRIORITY: Readonly<Record<string, number>> = { simulation_state: 0, intent_state: 1 };

export function buildTwinOverlays(
  sceneObjects: Record<string, DigitalTwinDeltaData["scene_object"]>,
  sceneObjectIdsNewestFirst: readonly string[],
): TwinOverlayObject[] {
  const seen = new Set<string>();
  const ordered = sceneObjectIdsNewestFirst.length > 0 ? sceneObjectIdsNewestFirst : Object.keys(sceneObjects).sort();
  const overlays: TwinOverlayObject[] = [];
  for (const overlayId of ordered) {
    if (seen.has(overlayId)) continue;
    seen.add(overlayId);
    const sceneObject = sceneObjects[overlayId];
    if (!sceneObject) continue;
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
  return overlays.sort((left, right) =>
    (OVERLAY_TYPE_PRIORITY[left.objectType] ?? 2) - (OVERLAY_TYPE_PRIORITY[right.objectType] ?? 2) || left.id.localeCompare(right.id));
}

/** Attach the visual heuristic to topology nodes (inspector/legacy consumers only). */
export function withCongestion<N extends TwinNode>(topology: TwinTopology<N>, congestionByDevice: Record<string, TwinCongestion>): TwinTopology<N & TwinSceneNode> {
  const nodes = topology.nodes.map((node) => ({ ...node, congestion: congestionByDevice[node.id] ?? NEUTRAL_CONGESTION }));
  const nodeById: Record<string, N & TwinSceneNode> = {};
  for (const node of nodes) nodeById[node.id] = node;
  return { nodes, links: topology.links, nodeById };
}

export function buildTwinSceneModel(input: SceneAdapterInput): TwinSceneModel {
  const topology = withCongestion(buildTwinTopology(input), deriveCongestionByDevice(input.telemetryByDeviceMetric, input.telemetryKeysNewestFirst, input.now));
  return { ...topology, overlays: buildTwinOverlays(input.sceneObjects, input.sceneObjectIdsNewestFirst) };
}

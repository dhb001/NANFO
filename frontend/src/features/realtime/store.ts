import { create } from "zustand";
import type { AlertDeltaData, DigitalTwinDeltaData, RealtimeHaltReason, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";

const MAX_ALERT_ITEMS = 200;
export const TELEMETRY_LIMITS = { resources: 300, metricsPerResource: 16, flowHistory: 300 } as const;
const MAX_SCENE_OBJECTS = 300;

export interface LiveAlertItem {
  event_id: string;
  event_type: string;
  source: string;
  payload: Record<string, unknown>;
  correlation_id?: string;
  timestamp?: string;
}

export type RealtimeChannel = "topology" | "telemetry" | "alerts" | "digitalTwin";

export interface RealtimeHalt {
  reason: RealtimeHaltReason;
  message: string;
}

type SceneScope = { workspaceId: string; networkId: string };

/** Frames queued by the bridge and applied together in one store update (ADR-028 burst batching). */
export interface LiveDeltaBatch {
  topology?: Array<{ delta: TopologyDeltaData; timestamp?: string }>;
  telemetry?: TelemetryDeltaData[];
  digitalTwin?: Array<{ delta: DigitalTwinDeltaData; timestamp?: string; scope?: SceneScope }>;
  alerts?: Array<{ delta: AlertDeltaData; context: { correlation_id?: string; timestamp?: string } }>;
}

interface LiveState {
  epoch: number;
  /** Channels stopped until the operator retries (ADR-028 C1 WS_CONNECTION_LIMIT). */
  realtimeHalts: Partial<Record<RealtimeChannel, RealtimeHalt>>;
  /** Bumped by the visible "Retry realtime" control; restarts halted sockets. */
  realtimeRetry: number;
  haltRealtime: (channel: RealtimeChannel, halt: RealtimeHalt) => void;
  retryRealtime: () => void;
  topologyRevision: number;
  topologyVersions: Record<string, { revision: number; timestamp: number }>;
  topologyTombstones: Record<string, number>;
  sceneObjectLastSeen: Record<string, number>;
  sceneObjectScopes: Record<string, SceneScope>;
  sceneObjectAvailability: Record<string, "pending" | "stale" | "reconciled">;
  sceneObjectServerRevisions: Record<string, number>;
  sceneReconciliation: { known: number; attempted: number; unavailable: number; omitted: number } | null;
  reconcileSceneObject: (id: string, expected: DigitalTwinDeltaData["scene_object"], epoch: number, result: { object: DigitalTwinDeltaData["scene_object"]; timestamp: string; revision?: number } | "remove" | "stale") => void;
  reconcileTopologySnapshot: (ids: string[], epoch: number, revision: number) => void;
  reset: () => void;
  topologyByDeviceId: Record<string, TopologyDeltaData["node"]>;
  telemetryByDeviceMetric: Record<string, TelemetryDeltaData["metric"]>;
  telemetryKeysNewestFirst: string[];
  sceneObjects: Record<string, DigitalTwinDeltaData["scene_object"]>;
  sceneObjectIdsNewestFirst: string[];
  alerts: LiveAlertItem[];
  topologyStatus: "connecting" | "open" | "closed";
  telemetryStatus: "connecting" | "open" | "closed";
  alertsStatus: "connecting" | "open" | "closed";
  digitalTwinStatus: "connecting" | "open" | "closed";
  /** Apply many queued frames with a single `set` (one render per flush). */
  applyDeltaBatch: (batch: LiveDeltaBatch) => void;
  applyTopologyDelta: (delta: TopologyDeltaData, timestamp?: string) => void;
  applyTelemetryDelta: (delta: TelemetryDeltaData) => void;
  applyDigitalTwinDelta: (delta: DigitalTwinDeltaData, timestamp?: string, scope?: SceneScope) => void;
  applyAlertDelta: (delta: AlertDeltaData, context: { correlation_id?: string; timestamp?: string }) => void;
  setConnectionStatus: (
    channel: RealtimeChannel,
    status: "connecting" | "open" | "closed",
  ) => void;
}

type Metric = TelemetryDeltaData["metric"];

export function metricKey(metric: Metric) {
  return JSON.stringify([metric.workspace_id, metric.network_id, metric.device_id, metric.metric, metric.unit, metric.source, metric.tags?.run_id ?? null, metric.tags?.port_no ?? null, metric.tags?.peer_host ?? null,
    metric.metric.startsWith("flow_") ? [metric.observed_at, metric.tags?.table_id, metric.tags?.cookie, metric.tags?.priority, metric.tags?.flow_index, metric.event_id] : null]);
}

// Identities are computed once per metric object, not once per retention pass.
const resourceKeys = new WeakMap<Metric, string>();
function resourceKey(metric: Metric) {
  let key = resourceKeys.get(metric);
  if (key === undefined) {
    key = `${metric.workspace_id}\u0000${metric.network_id}\u0000${metric.device_id}`;
    resourceKeys.set(metric, key);
  }
  return key;
}

function isValidMetric(metric: Metric | undefined): metric is Metric {
  return Boolean(metric) && typeof metric!.device_id === "string" && typeof metric!.metric === "string" &&
    typeof metric!.workspace_id === "string" && typeof metric!.network_id === "string" &&
    typeof metric!.source === "string" && typeof metric!.observed_at === "string" &&
    (metric!.unit === null || typeof metric!.unit === "string") && Boolean(metric!.tags) && typeof metric!.tags === "object" && !Array.isArray(metric!.tags) &&
    Number.isFinite(metric!.value);
}

// Latest metric identities and snapshot-local flow history have independent budgets.
// A noisy device can replace its own series, never consume another device's slots.
function retainTelemetry(keys: string[], metrics: LiveState["telemetryByDeviceMetric"]) {
  const resources = new Map<string, number>();
  let flows = 0;
  return keys.filter((key) => {
    const metric = metrics[key];
    let keep: boolean;
    if (metric.metric.startsWith("flow_")) {
      keep = ++flows <= TELEMETRY_LIMITS.flowHistory;
    } else {
      const resource = resourceKey(metric);
      const count = resources.get(resource) ?? 0;
      keep = count < TELEMETRY_LIMITS.metricsPerResource &&
        (count > 0 || resources.size < TELEMETRY_LIMITS.resources);
      if (keep) resources.set(resource, count + 1);
    }
    if (!keep) delete metrics[key];
    return keep;
  });
}

/** Most recently touched first (deduplicated), then the untouched previous order. */
function newestFirst(previous: readonly string[], touchedInOrder: readonly string[]) {
  const touched = new Set<string>();
  const front: string[] = [];
  for (let index = touchedInOrder.length - 1; index >= 0; index--) {
    const key = touchedInOrder[index];
    if (!touched.has(key)) {
      touched.add(key);
      front.push(key);
    }
  }
  return touched.size ? [...front, ...previous.filter((key) => !touched.has(key))] : [...previous];
}

function reduceTopology(state: LiveState, frames: NonNullable<LiveDeltaBatch["topology"]>): Partial<LiveState> | null {
  let topologyByDeviceId: LiveState["topologyByDeviceId"] | null = null;
  let topologyTombstones: LiveState["topologyTombstones"] | null = null;
  let topologyVersions: LiveState["topologyVersions"] | null = null;
  let revision = state.topologyRevision;
  for (const { delta, timestamp } of frames) {
    if (!delta?.node?.device_id || !["add", "update", "remove"].includes(delta.delta_type)) continue;
    const id = delta.node.device_id;
    const versions = topologyVersions ?? state.topologyVersions;
    const observed = timestamp === undefined ? Math.max(Date.now(), (versions[id]?.timestamp ?? 0) + 1) : Date.parse(timestamp);
    if (!Number.isFinite(observed) || observed <= (versions[id]?.timestamp ?? -Infinity)) continue;
    topologyByDeviceId ??= { ...state.topologyByDeviceId };
    topologyTombstones ??= { ...state.topologyTombstones };
    topologyVersions ??= { ...state.topologyVersions };
    revision += 1;
    if (delta.delta_type === "remove") {
      delete topologyByDeviceId[id];
      topologyTombstones[id] = revision;
    } else {
      delete topologyTombstones[id];
      topologyByDeviceId[id] = { ...(topologyByDeviceId[id] ?? {}), ...delta.node };
    }
    topologyVersions[id] = { revision, timestamp: observed };
  }
  return topologyByDeviceId ? { topologyByDeviceId, topologyTombstones: topologyTombstones!, topologyVersions: topologyVersions!, topologyRevision: revision } : null;
}

function reduceTelemetry(state: LiveState, deltas: NonNullable<LiveDeltaBatch["telemetry"]>): Partial<LiveState> | null {
  let metrics: LiveState["telemetryByDeviceMetric"] | null = null;
  const touched: string[] = [];
  for (const delta of deltas) {
    const metric = delta?.metric;
    if (!isValidMetric(metric)) continue;
    const observed = Date.parse(metric.observed_at);
    if (!Number.isFinite(observed)) continue;
    const key = metricKey(metric);
    const current = (metrics ?? state.telemetryByDeviceMetric)[key];
    if (current && observed <= Date.parse(current.observed_at)) continue;
    metrics ??= { ...state.telemetryByDeviceMetric };
    metrics[key] = metric;
    touched.push(key);
  }
  if (!metrics) return null;
  return {
    telemetryByDeviceMetric: metrics,
    telemetryKeysNewestFirst: retainTelemetry(newestFirst(state.telemetryKeysNewestFirst, touched), metrics),
  };
}

function sceneObjectId(object: DigitalTwinDeltaData["scene_object"]) {
  return object.object_type === "simulation_state" && object.simulation_id
    ? `simulation:${object.simulation_id}`
    : object.object_type === "intent_state" && object.intent_id ? `intent:${object.intent_id}` : object.id;
}

function reduceDigitalTwin(state: LiveState, frames: NonNullable<LiveDeltaBatch["digitalTwin"]>): Partial<LiveState> | null {
  let sceneObjects: LiveState["sceneObjects"] | null = null;
  let lastSeen: LiveState["sceneObjectLastSeen"] = state.sceneObjectLastSeen;
  let scopes: LiveState["sceneObjectScopes"] = state.sceneObjectScopes;
  let availability: LiveState["sceneObjectAvailability"] = state.sceneObjectAvailability;
  const touched: string[] = [];
  for (const { delta, timestamp, scope } of frames) {
    const object = delta?.scene_object;
    if (!object?.id || delta.delta_type !== "update") continue;
    const objectId = sceneObjectId(object);
    const observed = timestamp === undefined ? Math.max(Date.now(), (lastSeen[objectId] ?? 0) + 1) : Date.parse(timestamp);
    if (!Number.isFinite(observed) || observed <= (lastSeen[objectId] ?? -Infinity)) continue;
    if (!sceneObjects) {
      sceneObjects = { ...state.sceneObjects };
      lastSeen = { ...state.sceneObjectLastSeen };
      scopes = { ...state.sceneObjectScopes };
      availability = { ...state.sceneObjectAvailability };
    }
    lastSeen[objectId] = observed;
    if (scope) scopes[objectId] = scope;
    availability[objectId] = "stale";
    sceneObjects[objectId] = { ...(sceneObjects[objectId] ?? {}), ...object, id: objectId };
    touched.push(objectId);
  }
  if (!sceneObjects) return null;
  const ordered = newestFirst(state.sceneObjectIdsNewestFirst, touched);
  const sceneObjectServerRevisions = { ...state.sceneObjectServerRevisions };
  for (const evicted of ordered.slice(MAX_SCENE_OBJECTS)) {
    delete sceneObjects[evicted]; delete lastSeen[evicted]; delete scopes[evicted]; delete availability[evicted]; delete sceneObjectServerRevisions[evicted];
  }
  return {
    sceneObjects, sceneObjectLastSeen: lastSeen, sceneObjectScopes: scopes, sceneObjectAvailability: availability,
    sceneObjectServerRevisions, sceneObjectIdsNewestFirst: ordered.slice(0, MAX_SCENE_OBJECTS),
  };
}

function reduceAlerts(state: LiveState, frames: NonNullable<LiveDeltaBatch["alerts"]>): Partial<LiveState> | null {
  const incoming = frames.filter(({ delta }) => delta?.alert).map(({ delta, context }) => ({
    ...delta.alert, payload: delta.alert.payload, correlation_id: context.correlation_id, timestamp: context.timestamp,
  }));
  if (!incoming.length) return null;
  const seen = new Set<string>();
  const next: LiveAlertItem[] = [];
  for (const alert of [...incoming.reverse(), ...state.alerts]) {
    if (seen.has(alert.event_id)) continue;
    seen.add(alert.event_id);
    next.push(alert);
    if (next.length === MAX_ALERT_ITEMS) break;
  }
  return { alerts: next };
}

/** Pure batch reducer: returns the same state object when nothing applies. */
export function reduceDeltaBatch(state: LiveState, batch: LiveDeltaBatch): LiveState | Partial<LiveState> {
  const changes: Partial<LiveState> = {};
  let changed = false;
  let working = state;
  for (const reduce of [
    batch.topology?.length ? () => reduceTopology(working, batch.topology!) : null,
    batch.telemetry?.length ? () => reduceTelemetry(working, batch.telemetry!) : null,
    batch.digitalTwin?.length ? () => reduceDigitalTwin(working, batch.digitalTwin!) : null,
    batch.alerts?.length ? () => reduceAlerts(working, batch.alerts!) : null,
  ]) {
    const partial = reduce?.();
    if (partial) {
      Object.assign(changes, partial);
      working = { ...working, ...partial };
      changed = true;
    }
  }
  return changed ? changes : state;
}

export const useLiveStore = create<LiveState>((set) => ({
  epoch: 0,
  realtimeHalts: {},
  realtimeRetry: 0,
  haltRealtime: (channel, halt) => set((state) => ({ realtimeHalts: { ...state.realtimeHalts, [channel]: halt } })),
  retryRealtime: () => set((state) => ({ realtimeHalts: {}, realtimeRetry: state.realtimeRetry + 1 })),
  topologyRevision: 0,
  topologyVersions: {},
  topologyTombstones: {},
  sceneObjectLastSeen: {},
  sceneObjectScopes: {}, sceneObjectAvailability: {}, sceneObjectServerRevisions: {}, sceneReconciliation: null,
  reset: () => set((state) => ({
    epoch: state.epoch + 1, realtimeHalts: {}, topologyRevision: 0, topologyVersions: {}, topologyTombstones: {}, sceneObjectLastSeen: {},
    sceneObjectScopes: {}, sceneObjectAvailability: {}, sceneObjectServerRevisions: {}, sceneReconciliation: null,
    topologyByDeviceId: {}, telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [],
    sceneObjects: {}, sceneObjectIdsNewestFirst: [], alerts: [],
    topologyStatus: "closed", telemetryStatus: "closed", alertsStatus: "closed", digitalTwinStatus: "closed",
  })),
  reconcileSceneObject: (id, expected, epoch, result) => set((state) => {
    if (state.epoch !== epoch || state.sceneObjects[id] !== expected) return state;
    if (result === "stale") return { sceneObjectAvailability: { ...state.sceneObjectAvailability, [id]: "stale" } };
    if (result === "remove") {
      const sceneObjects = { ...state.sceneObjects };
      const sceneObjectScopes = { ...state.sceneObjectScopes };
      const sceneObjectAvailability = { ...state.sceneObjectAvailability };
      const sceneObjectLastSeen = { ...state.sceneObjectLastSeen };
      const sceneObjectServerRevisions = { ...state.sceneObjectServerRevisions };
      delete sceneObjects[id]; delete sceneObjectScopes[id]; delete sceneObjectAvailability[id]; delete sceneObjectLastSeen[id]; delete sceneObjectServerRevisions[id];
      return { sceneObjects, sceneObjectScopes, sceneObjectAvailability, sceneObjectLastSeen, sceneObjectServerRevisions,
        sceneObjectIdsNewestFirst: state.sceneObjectIdsNewestFirst.filter((key) => key !== id) };
    }
    const observed = Date.parse(result.timestamp);
    const revision = result.revision;
    if (!Number.isFinite(observed) || observed < (state.sceneObjectLastSeen[id] ?? -Infinity) ||
        (revision !== undefined && (!Number.isSafeInteger(revision) || revision < (state.sceneObjectServerRevisions[id] ?? 0)))) {
      return { sceneObjectAvailability: { ...state.sceneObjectAvailability, [id]: "stale" } };
    }
    return { sceneObjects: { ...state.sceneObjects, [id]: { ...result.object, id } },
      sceneObjectLastSeen: { ...state.sceneObjectLastSeen, [id]: observed },
      sceneObjectAvailability: { ...state.sceneObjectAvailability, [id]: "reconciled" },
      sceneObjectServerRevisions: revision === undefined ? state.sceneObjectServerRevisions : { ...state.sceneObjectServerRevisions, [id]: revision } };
  }),
  reconcileTopologySnapshot: (ids, epoch, revision) => set((state) => {
    if (state.epoch !== epoch) return state;
    const present = new Set(ids);
    let topologyByDeviceId: LiveState["topologyByDeviceId"] | null = null;
    let topologyTombstones: LiveState["topologyTombstones"] | null = null;
    // Only a complete REST snapshot started after the delta can retire its overlay.
    for (const [id, version] of Object.entries(state.topologyVersions)) {
      if (version.revision > revision) continue;
      if (Object.hasOwn(state.topologyByDeviceId, id)) {
        topologyByDeviceId ??= { ...state.topologyByDeviceId };
        delete topologyByDeviceId[id];
      }
      if (!present.has(id) && Object.hasOwn(state.topologyTombstones, id)) {
        topologyTombstones ??= { ...state.topologyTombstones };
        delete topologyTombstones[id];
      }
    }
    // Unchanged snapshots (for example after a cache patch) do not re-render subscribers.
    if (!topologyByDeviceId && !topologyTombstones) return state;
    return { topologyByDeviceId: topologyByDeviceId ?? state.topologyByDeviceId, topologyTombstones: topologyTombstones ?? state.topologyTombstones };
  }),
  topologyByDeviceId: {},
  telemetryByDeviceMetric: {},
  telemetryKeysNewestFirst: [],
  sceneObjects: {},
  sceneObjectIdsNewestFirst: [],
  alerts: [],
  topologyStatus: "closed",
  telemetryStatus: "closed",
  alertsStatus: "closed",
  digitalTwinStatus: "closed",
  applyDeltaBatch: (batch) => set((state) => reduceDeltaBatch(state, batch)),
  applyTopologyDelta: (delta, timestamp) => set((state) => reduceDeltaBatch(state, { topology: [{ delta, timestamp }] })),
  applyTelemetryDelta: (delta) => set((state) => reduceDeltaBatch(state, { telemetry: [delta] })),
  applyDigitalTwinDelta: (delta, timestamp, scope) => set((state) => reduceDeltaBatch(state, { digitalTwin: [{ delta, timestamp, scope }] })),
  applyAlertDelta: (delta, context) => set((state) => reduceDeltaBatch(state, { alerts: [{ delta, context }] })),
  setConnectionStatus: (channel, status) =>
    set((state) => {
      const field = channel === "topology" ? "topologyStatus" : channel === "telemetry" ? "telemetryStatus"
        : channel === "alerts" ? "alertsStatus" : "digitalTwinStatus";
      return state[field] === status ? state : { [field]: status };
    }),
}));

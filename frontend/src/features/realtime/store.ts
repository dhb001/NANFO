import { create } from "zustand";
import { AlertDeltaData, DigitalTwinDeltaData, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";

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

interface LiveState {
  epoch: number;
  topologyRevision: number;
  topologyVersions: Record<string, { revision: number; timestamp: number }>;
  topologyTombstones: Record<string, number>;
  sceneObjectLastSeen: Record<string, number>;
  sceneObjectScopes: Record<string, { workspaceId: string; networkId: string }>;
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
  applyTopologyDelta: (delta: TopologyDeltaData, timestamp?: string) => void;
  applyTelemetryDelta: (delta: TelemetryDeltaData) => void;
  applyDigitalTwinDelta: (delta: DigitalTwinDeltaData, timestamp?: string, scope?: { workspaceId: string; networkId: string }) => void;
  applyAlertDelta: (delta: AlertDeltaData, context: { correlation_id?: string; timestamp?: string }) => void;
  setConnectionStatus: (
    channel: "topology" | "telemetry" | "alerts" | "digitalTwin",
    status: "connecting" | "open" | "closed",
  ) => void;
}

function metricKey(metric: TelemetryDeltaData["metric"]) {
  return JSON.stringify([metric.workspace_id, metric.network_id, metric.device_id, metric.metric, metric.unit, metric.source, metric.tags?.run_id ?? null, metric.tags?.port_no ?? null, metric.tags?.peer_host ?? null,
    metric.metric.startsWith("flow_") ? [metric.observed_at, metric.tags?.table_id, metric.tags?.cookie, metric.tags?.priority, metric.tags?.flow_index, metric.event_id] : null]);
}

function resourceKey(metric: TelemetryDeltaData["metric"]) {
  return JSON.stringify([metric.workspace_id, metric.network_id, metric.device_id]);
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

function pushNewestKey(keys: string[], key: string, maxItems: number) {
  const withoutKey = keys.filter((item) => item !== key);
  const nextKeys = [key, ...withoutKey];
  if (nextKeys.length <= maxItems) {
    return {
      nextKeys,
      evictedKeys: [] as string[],
    };
  }

  return {
    nextKeys: nextKeys.slice(0, maxItems),
    evictedKeys: nextKeys.slice(maxItems),
  };
}

export const useLiveStore = create<LiveState>((set) => ({
  epoch: 0,
  topologyRevision: 0,
  topologyVersions: {},
  topologyTombstones: {},
  sceneObjectLastSeen: {},
  sceneObjectScopes: {}, sceneObjectAvailability: {}, sceneObjectServerRevisions: {}, sceneReconciliation: null,
  reset: () => set((state) => ({
    epoch: state.epoch + 1, topologyRevision: 0, topologyVersions: {}, topologyTombstones: {}, sceneObjectLastSeen: {},
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
    const topologyByDeviceId = { ...state.topologyByDeviceId };
    const topologyTombstones = { ...state.topologyTombstones };
    // Only a complete REST snapshot started after the delta can retire its overlay.
    for (const [id, version] of Object.entries(state.topologyVersions)) {
      if (version.revision > revision) continue;
      delete topologyByDeviceId[id];
      if (!present.has(id)) delete topologyTombstones[id];
    }
    return { topologyByDeviceId, topologyTombstones };
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
  applyTopologyDelta: (delta, timestamp) =>
    set((state) => {
      if (!delta.node?.device_id || !["add", "update", "remove"].includes(delta.delta_type)) return state;
      const id = delta.node.device_id;
      const observed = timestamp === undefined ? Math.max(Date.now(), (state.topologyVersions[id]?.timestamp ?? 0) + 1) : Date.parse(timestamp);
      if (!Number.isFinite(observed) || observed <= (state.topologyVersions[id]?.timestamp ?? -Infinity)) return state;
      const revision = state.topologyRevision + 1;
      const current = { ...state.topologyByDeviceId };
      const topologyTombstones = { ...state.topologyTombstones };
      if (delta.delta_type === "remove") {
        delete current[delta.node.device_id];
        topologyTombstones[id] = revision;
      } else {
        delete topologyTombstones[id];
        current[delta.node.device_id] = {
          ...(current[delta.node.device_id] ?? {}),
          ...delta.node,
        };
      }
      return { topologyByDeviceId: current, topologyTombstones, topologyRevision: revision,
        topologyVersions: { ...state.topologyVersions, [id]: { revision, timestamp: observed } } };
    }),
  applyTelemetryDelta: (delta) =>
    set((state) => {
      if (!delta.metric || typeof delta.metric.device_id !== "string" || typeof delta.metric.metric !== "string" ||
          typeof delta.metric.workspace_id !== "string" || typeof delta.metric.network_id !== "string" ||
          typeof delta.metric.source !== "string" || typeof delta.metric.observed_at !== "string" ||
          (delta.metric.unit !== null && typeof delta.metric.unit !== "string") || !delta.metric.tags || typeof delta.metric.tags !== "object" || Array.isArray(delta.metric.tags)) return state;
      const key = metricKey(delta.metric);
      const observed = Date.parse(delta.metric.observed_at);
      if (!Number.isFinite(observed) || !Number.isFinite(delta.metric.value) ||
          observed <= Date.parse(state.telemetryByDeviceMetric[key]?.observed_at ?? "")) return state;
      const nextMetrics = {
        ...state.telemetryByDeviceMetric,
        [key]: delta.metric,
      };

      const nextKeys = retainTelemetry(
        [key, ...state.telemetryKeysNewestFirst.filter((item) => item !== key)], nextMetrics,
      );

      return {
        telemetryByDeviceMetric: nextMetrics,
        telemetryKeysNewestFirst: nextKeys,
      };
    }),
  applyDigitalTwinDelta: (delta, timestamp, scope) =>
    set((state) => {
      const object = delta.scene_object;
      if (!object?.id || delta.delta_type !== "update") return state;
      const objectId = object.object_type === "simulation_state" && object.simulation_id
        ? `simulation:${object.simulation_id}`
        : object.object_type === "intent_state" && object.intent_id ? `intent:${object.intent_id}` : object.id;
      const observed = timestamp === undefined ? Math.max(Date.now(), (state.sceneObjectLastSeen[objectId] ?? 0) + 1) : Date.parse(timestamp);
      if (!Number.isFinite(observed) || observed <= (state.sceneObjectLastSeen[objectId] ?? -Infinity)) return state;
      const sceneObjectLastSeen = { ...state.sceneObjectLastSeen, [objectId]: observed };
      const sceneObjectScopes = { ...state.sceneObjectScopes, ...(scope ? { [objectId]: scope } : {}) };
      const sceneObjectAvailability = { ...state.sceneObjectAvailability, [objectId]: "stale" as const };
      const sceneObjectServerRevisions = { ...state.sceneObjectServerRevisions };
      const nextSceneObjects = {
        ...state.sceneObjects,
        [objectId]: {
          ...(state.sceneObjects[objectId] ?? {}),
          ...delta.scene_object,
          id: objectId,
        },
      };

      const { nextKeys, evictedKeys } = pushNewestKey(
        state.sceneObjectIdsNewestFirst,
        objectId,
        MAX_SCENE_OBJECTS,
      );

      for (const evictedId of evictedKeys) {
        delete nextSceneObjects[evictedId];
        delete sceneObjectLastSeen[evictedId];
        delete sceneObjectScopes[evictedId]; delete sceneObjectAvailability[evictedId]; delete sceneObjectServerRevisions[evictedId];
      }

      return {
        sceneObjects: nextSceneObjects,
        sceneObjectLastSeen,
        sceneObjectScopes, sceneObjectAvailability, sceneObjectServerRevisions,
        sceneObjectIdsNewestFirst: nextKeys,
      };
    }),
  applyAlertDelta: (delta, context) =>
    set((state) => {
      const alert = {
        ...delta.alert,
        payload: delta.alert.payload,
        correlation_id: context.correlation_id,
        timestamp: context.timestamp,
      };

      const deduped = state.alerts.filter((item) => item.event_id !== alert.event_id);
      const next = [alert, ...deduped].slice(0, MAX_ALERT_ITEMS);
      return { alerts: next };
    }),
  setConnectionStatus: (channel, status) =>
    set(() => {
      if (channel === "topology") {
        return { topologyStatus: status };
      }
      if (channel === "telemetry") {
        return { telemetryStatus: status };
      }
      if (channel === "alerts") {
        return { alertsStatus: status };
      }
      return { digitalTwinStatus: status };
    }),
}));

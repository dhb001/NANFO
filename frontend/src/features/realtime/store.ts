import { create } from "zustand";
import { AlertDeltaData, DigitalTwinDeltaData, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";

const MAX_ALERT_ITEMS = 200;
const MAX_TELEMETRY_METRICS = 300;
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
  applyTopologyDelta: (delta: TopologyDeltaData) => void;
  applyTelemetryDelta: (delta: TelemetryDeltaData) => void;
  applyDigitalTwinDelta: (delta: DigitalTwinDeltaData) => void;
  applyAlertDelta: (delta: AlertDeltaData, context: { correlation_id?: string; timestamp?: string }) => void;
  setConnectionStatus: (
    channel: "topology" | "telemetry" | "alerts" | "digitalTwin",
    status: "connecting" | "open" | "closed",
  ) => void;
}

function metricKey(metric: TelemetryDeltaData["metric"]) {
  return `${metric.device_id}:${metric.metric}`;
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
  applyTopologyDelta: (delta) =>
    set((state) => {
      const current = { ...state.topologyByDeviceId };
      if (delta.delta_type === "remove") {
        delete current[delta.node.device_id];
      } else {
        current[delta.node.device_id] = {
          ...(current[delta.node.device_id] ?? {}),
          ...delta.node,
        };
      }
      return { topologyByDeviceId: current };
    }),
  applyTelemetryDelta: (delta) =>
    set((state) => {
      const key = metricKey(delta.metric);
      const nextMetrics = {
        ...state.telemetryByDeviceMetric,
        [key]: delta.metric,
      };

      const { nextKeys, evictedKeys } = pushNewestKey(
        state.telemetryKeysNewestFirst,
        key,
        MAX_TELEMETRY_METRICS,
      );

      for (const evictedKey of evictedKeys) {
        delete nextMetrics[evictedKey];
      }

      return {
        telemetryByDeviceMetric: nextMetrics,
        telemetryKeysNewestFirst: nextKeys,
      };
    }),
  applyDigitalTwinDelta: (delta) =>
    set((state) => {
      const objectId = delta.scene_object.id;
      const nextSceneObjects = {
        ...state.sceneObjects,
        [objectId]: {
          ...(state.sceneObjects[objectId] ?? {}),
          ...delta.scene_object,
        },
      };

      const { nextKeys, evictedKeys } = pushNewestKey(
        state.sceneObjectIdsNewestFirst,
        objectId,
        MAX_SCENE_OBJECTS,
      );

      for (const evictedId of evictedKeys) {
        delete nextSceneObjects[evictedId];
      }

      return {
        sceneObjects: nextSceneObjects,
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

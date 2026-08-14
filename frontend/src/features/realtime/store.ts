import { create } from "zustand";
import { AlertDeltaData, DigitalTwinDeltaData, TelemetryDeltaData, TopologyDeltaData } from "@/shared/types/ws";

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
  sceneObjects: Record<string, DigitalTwinDeltaData["scene_object"]>;
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

export const useLiveStore = create<LiveState>((set) => ({
  topologyByDeviceId: {},
  telemetryByDeviceMetric: {},
  sceneObjects: {},
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
    set((state) => ({
      telemetryByDeviceMetric: {
        ...state.telemetryByDeviceMetric,
        [metricKey(delta.metric)]: delta.metric,
      },
    })),
  applyDigitalTwinDelta: (delta) =>
    set((state) => ({
      sceneObjects: {
        ...state.sceneObjects,
        [delta.scene_object.id]: {
          ...(state.sceneObjects[delta.scene_object.id] ?? {}),
          ...delta.scene_object,
        },
      },
    })),
  applyAlertDelta: (delta, context) =>
    set((state) => {
      const alert = {
        ...delta.alert,
        payload: delta.alert.payload,
        correlation_id: context.correlation_id,
        timestamp: context.timestamp,
      };

      const deduped = state.alerts.filter((item) => item.event_id !== alert.event_id);
      const next = [alert, ...deduped].slice(0, 200);
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

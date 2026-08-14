import { useCallback } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useManagedWebSocket } from "@/shared/realtime/useManagedWebSocket";
import { useLiveStore } from "@/features/realtime/store";
import {
  AlertDeltaData,
  DigitalTwinDeltaData,
  TelemetryDeltaData,
  TopologyDeltaData,
  WebSocketEnvelope,
} from "@/shared/types/ws";

function isTopologyFrame(frame: WebSocketEnvelope<unknown>): frame is WebSocketEnvelope<TopologyDeltaData> {
  return (
    (frame.event.startsWith("topology.") || frame.event.startsWith("network.device.")) &&
    typeof frame.data === "object"
  );
}

function isTelemetryFrame(frame: WebSocketEnvelope<unknown>): frame is WebSocketEnvelope<TelemetryDeltaData> {
  return frame.event.startsWith("telemetry.") && typeof frame.data === "object";
}

function isAlertFrame(frame: WebSocketEnvelope<unknown>): frame is WebSocketEnvelope<AlertDeltaData> {
  return frame.event.startsWith("alert.") && typeof frame.data === "object";
}

function isDigitalTwinFrame(frame: WebSocketEnvelope<unknown>): frame is WebSocketEnvelope<DigitalTwinDeltaData> {
  return (
    (frame.event.startsWith("simulation.") || frame.event.startsWith("intent.")) &&
    typeof frame.data === "object"
  );
}

export function RealtimeBridge() {
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const clearSession = useAuthStore((state) => state.clearSession);

  const applyTopologyDelta = useLiveStore((state) => state.applyTopologyDelta);
  const applyTelemetryDelta = useLiveStore((state) => state.applyTelemetryDelta);
  const applyAlertDelta = useLiveStore((state) => state.applyAlertDelta);
  const applyDigitalTwinDelta = useLiveStore((state) => state.applyDigitalTwinDelta);
  const setConnectionStatus = useLiveStore((state) => state.setConnectionStatus);

  const onUnauthorized = useCallback(() => {
    clearSession();
  }, [clearSession]);

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    path: "/ws/topology",
    token,
    channel: "topology",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && networkId),
    onUnauthorized,
    onStatusChange: (status) => setConnectionStatus("topology", status),
    onFrame: (frame) => {
      if (isTopologyFrame(frame) && frame.data?.node) {
        applyTopologyDelta(frame.data);
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    path: "/ws/telemetry",
    token,
    channel: "telemetry",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && networkId),
    onUnauthorized,
    onStatusChange: (status) => setConnectionStatus("telemetry", status),
    onFrame: (frame) => {
      if (isTelemetryFrame(frame) && frame.data?.metric) {
        applyTelemetryDelta(frame.data);
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    path: "/ws/alerts",
    token,
    channel: "alerts",
    filters: {},
    enabled: Boolean(token),
    onUnauthorized,
    onStatusChange: (status) => setConnectionStatus("alerts", status),
    onFrame: (frame) => {
      if (isAlertFrame(frame) && frame.data?.alert) {
        applyAlertDelta(frame.data, {
          correlation_id: frame.correlation_id,
          timestamp: frame.timestamp,
        });
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    path: "/ws/digital-twin",
    token,
    channel: "digital-twin",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && networkId),
    onUnauthorized,
    onStatusChange: (status) => setConnectionStatus("digitalTwin", status),
    onFrame: (frame) => {
      if (isDigitalTwinFrame(frame) && frame.data?.scene_object) {
        applyDigitalTwinDelta(frame.data);
      }
    },
  });

  return null;
}

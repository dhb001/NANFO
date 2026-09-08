import { useCallback, useRef } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useManagedWebSocket } from "@/shared/realtime/useManagedWebSocket";
import { useLiveStore } from "@/features/realtime/store";
import { recoverSocketUpgrade, refreshSession } from "@/features/auth/session";
import { hasPermission } from "@/features/auth/permissions";
import { useUiStore } from "@/shared/state/ui-store";
import {
  AlertDeltaData,
  DigitalTwinDeltaData,
  TelemetryDeltaData,
  TopologyDeltaData,
  WebSocketErrorData,
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
  const userId = useAuthStore((state) => state.userId);
  const generation = useAuthStore((state) => state.generation);
  const endingSession = useAuthStore((state) => state.endingSession);
  const profile = useAuthStore((state) => state.profile);
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const pushToast = useUiStore((state) => state.pushToast);

  const contextKey = JSON.stringify([generation, userId, organizationId, workspaceId, networkId, profile?.permissions]);
  const isCurrent = useCallback(() => {
    const auth = useAuthStore.getState();
    const scope = useWorkspaceStore.getState();
    return !auth.endingSession && auth.accessToken === token &&
      JSON.stringify([auth.generation, auth.userId, scope.organizationId, scope.workspaceId, scope.networkId, auth.profile?.permissions]) === contextKey;
  }, [token, contextKey]);
  const scoped = { contextKey, isCurrent, onUpgradeFailure: recoverSocketUpgrade };
  const lastToastByCodeRef = useRef<Record<string, number>>({});

  const applyTopologyDelta = useLiveStore((state) => state.applyTopologyDelta);
  const applyTelemetryDelta = useLiveStore((state) => state.applyTelemetryDelta);
  const applyAlertDelta = useLiveStore((state) => state.applyAlertDelta);
  const applyDigitalTwinDelta = useLiveStore((state) => state.applyDigitalTwinDelta);
  const setConnectionStatus = useLiveStore((state) => state.setConnectionStatus);

  const showSocketErrorToast = useCallback(
    (error: WebSocketErrorData) => {
      if (error.code === "WS_UNAUTHORIZED") {
        return;
      }

      const now = Date.now();
      const lastShownAt = lastToastByCodeRef.current[error.code] ?? 0;
      if (now - lastShownAt < 3000) {
        return;
      }

      lastToastByCodeRef.current[error.code] = now;

      const titleByCode: Record<string, string> = {
        WS_BACKPRESSURE: "Realtime backlog detected",
        WS_UNKNOWN_CHANNEL: "Realtime channel mismatch",
        WS_INVALID_FILTER: "Realtime filter rejected",
      };

      pushToast({
        tone: error.code === "WS_BACKPRESSURE" ? "warn" : "danger",
        title: titleByCode[error.code] ?? "Realtime channel error",
        description: error.message,
      });
    },
    [pushToast],
  );

  const onUnauthorized = useCallback(() => {
    void refreshSession();
  }, []);

  const onSocketError = useCallback(
    (error: WebSocketErrorData) => {
      showSocketErrorToast(error);
    },
    [showSocketErrorToast],
  );

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/topology",
    token,
    channel: "topology",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && workspaceId && networkId && !endingSession && hasPermission(profile, "read:topology")),
    onUnauthorized,
    onError: onSocketError,
    onStatusChange: (status) => setConnectionStatus("topology", status),
    onFrame: (frame) => {
      if (isTopologyFrame(frame) && frame.data?.node) {
        applyTopologyDelta(frame.data);
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/telemetry",
    token,
    channel: "telemetry",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && workspaceId && networkId && !endingSession && hasPermission(profile, "read:telemetry")),
    onUnauthorized,
    onError: onSocketError,
    onStatusChange: (status) => setConnectionStatus("telemetry", status),
    onFrame: (frame) => {
      if (isTelemetryFrame(frame) && frame.data?.metric &&
          frame.data.metric.workspace_id === workspaceId && frame.data.metric.network_id === networkId) {
        applyTelemetryDelta(frame.data);
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/alerts",
    token,
    channel: "alerts",
    filters: {},
    enabled: Boolean(token && workspaceId && !endingSession && hasPermission(profile, "read:telemetry")),
    onUnauthorized,
    onError: onSocketError,
    onStatusChange: (status) => setConnectionStatus("alerts", status),
    onFrame: (frame) => {
      if (isAlertFrame(frame) && frame.data?.alert) {
        // Alerts has no documented subscription filter. Fail closed on unscoped payloads.
        const payload = frame.data.alert.payload;
        if (payload.workspace_id !== workspaceId || (networkId && payload.network_id !== networkId)) return;
        applyAlertDelta(frame.data, {
          correlation_id: frame.correlation_id,
          timestamp: frame.timestamp,
        });
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/digital-twin",
    token,
    channel: "digital-twin",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && workspaceId && networkId && !endingSession && hasPermission(profile, "read:topology")),
    onUnauthorized,
    onError: onSocketError,
    onStatusChange: (status) => setConnectionStatus("digitalTwin", status),
    onFrame: (frame) => {
      if (isDigitalTwinFrame(frame) && frame.data?.scene_object) {
        applyDigitalTwinDelta(frame.data);
      }
    },
  });

  return null;
}

import { useCallback, useRef } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useManagedWebSocket } from "@/shared/realtime/useManagedWebSocket";
import { useLiveStore } from "@/features/realtime/store";
import { refresh } from "@/features/auth/api";
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
  const refreshToken = useAuthStore((state) => state.refreshToken);
  const userId = useAuthStore((state) => state.userId);
  const setSession = useAuthStore((state) => state.setSession);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const clearSession = useAuthStore((state) => state.clearSession);
  const pushToast = useUiStore((state) => state.pushToast);

  const refreshInFlightRef = useRef<Promise<boolean> | null>(null);
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

  const refreshSession = useCallback(async () => {
    if (!refreshToken || !userId) {
      clearSession();
      return false;
    }

    if (refreshInFlightRef.current) {
      return refreshInFlightRef.current;
    }

    const task = (async () => {
      try {
        const nextToken = await refresh(refreshToken);
        setSession({
          accessToken: nextToken.access_token,
          refreshToken,
          userId,
        });
        return true;
      } catch {
        clearSession();
        return false;
      } finally {
        refreshInFlightRef.current = null;
      }
    })();

    refreshInFlightRef.current = task;
    return task;
  }, [clearSession, refreshToken, setSession, userId]);

  const onUnauthorized = useCallback(() => {
    void refreshSession();
  }, [refreshSession]);

  const onSocketError = useCallback(
    (error: WebSocketErrorData) => {
      showSocketErrorToast(error);
    },
    [showSocketErrorToast],
  );

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    path: "/ws/topology",
    token,
    channel: "topology",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && networkId),
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
    path: "/ws/telemetry",
    token,
    channel: "telemetry",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && networkId),
    onUnauthorized,
    onError: onSocketError,
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
    onError: onSocketError,
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

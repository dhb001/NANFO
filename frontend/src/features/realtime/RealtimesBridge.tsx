import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useManagedWebSocket } from "@/shared/realtime/useManagedWebSocket";
import { useLiveStore } from "@/features/realtime/store";
import { recoverSocketUpgrade, refreshSession } from "@/features/auth/session";
import { hasPermission } from "@/features/auth/permissions";
import { authorityKey, useSessionScope } from "@/features/auth/sessionScope";
import { useUiStore } from "@/shared/state/ui-store";
import { reconcileKnownScenes } from "./reconcileScenes";
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
  const queryClient = useQueryClient();
  const token = useAuthStore((state) => state.accessToken);
  const userId = useAuthStore((state) => state.userId);
  const generation = useAuthStore((state) => state.generation);
  const endingSession = useAuthStore((state) => state.endingSession);
  const profile = useAuthStore((state) => state.profile);
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const session = useSessionScope();

  const contextKey = JSON.stringify([generation, userId, organizationId, workspaceId, networkId, session.authority]);
  const epoch = useLiveStore((state) => state.epoch);
  const isScopeCurrent = useCallback(() => {
    const auth = useAuthStore.getState();
    const scope = useWorkspaceStore.getState();
    return !auth.endingSession && Boolean(auth.accessToken) && useLiveStore.getState().epoch === epoch &&
      JSON.stringify([auth.generation, auth.userId, scope.organizationId, scope.workspaceId, scope.networkId, authorityKey(auth.profile)]) === contextKey;
  }, [contextKey, epoch]);
  const isCurrent = useCallback(() => isScopeCurrent() && useAuthStore.getState().accessToken === token, [isScopeCurrent, token]);
  const scoped = { contextKey, isCurrent, onUpgradeFailure: recoverSocketUpgrade };
  const lastToastByCodeRef = useRef<Record<string, number>>({});
  const reconcileTimer = useRef<number | null>(null);
  const pendingChannels = useRef(new Set<string>());
  const sceneAbort = useRef<AbortController | null>(null);
  useEffect(() => () => {
    if (reconcileTimer.current !== null) window.clearTimeout(reconcileTimer.current);
    reconcileTimer.current = null;
    pendingChannels.current.clear();
    sceneAbort.current?.abort();
  }, [contextKey, epoch]);

  const reconcile = useCallback(function queueReconciliation(channel: string) {
    if (!isScopeCurrent()) return;
    pendingChannels.current.add(channel);
    if (reconcileTimer.current !== null) return;
    const timer = window.setTimeout(() => {
      const channels = new Set(pendingChannels.current);
      pendingChannels.current.clear();
      if (!isScopeCurrent()) return;
      const token = useAuthStore.getState().accessToken!;
      const graph = queryClient.getQueryData<{ data: { nodes: { device_id: string }[] } }>(["topology", token, networkId]);
      const deviceIds = new Set(graph?.data.nodes.map((node) => node.device_id));
      const controller = new AbortController();
      sceneAbort.current = controller;
      const scenes = channels.has("digitalTwin") && token && workspaceId && networkId && hasPermission(useAuthStore.getState().profile, "read:topology")
        ? reconcileKnownScenes(token, workspaceId, networkId, isScopeCurrent, controller.signal, () => useAuthStore.getState().accessToken!) : Promise.resolve();
      void Promise.all([scenes, queryClient.invalidateQueries({ predicate: (query) => {
        const key = query.queryKey;
        if (channels.has("topology") && key[1] === token) {
          if (key[0] === "networks") return key[2] === workspaceId;
          if (key[0] === "topology" || key[0] === "devices") return key[2] === networkId;
          if (["topology-node", "topology-neighbours", "topology-impact"].includes(String(key[0]))) return deviceIds.has(String(key[2]));
        }
        if (channels.has("telemetry") && key[0] === "telemetry" && key[2] === session.key && key[3] === session.authority) {
          // Device reads are already tenant-bound, including devices outside a
          // partial/unmounted graph or beyond the first inventory page.
          if (key[1] === "device") return true;
          if (key[1] === "history") {
            const scope = key[4] as { networkId?: string; workspaceId?: string } | undefined;
            return (!scope?.workspaceId || scope.workspaceId === workspaceId) &&
              (scope?.networkId ? scope.networkId === networkId : scope?.workspaceId === workspaceId);
          }
        }
        if (channels.has("alerts") && key[0] === "alerts" && key[1] === token) {
          const options = key[2];
          if (options && typeof options === "object") {
            const scope = options as { workspaceId?: string; networkId?: string };
            return (!scope.workspaceId || scope.workspaceId === workspaceId) && (!scope.networkId || scope.networkId === networkId);
          }
          // Detail/history have only an ID in their key. Require cached owner
          // evidence rather than invalidating another network's inspected alert.
          const detail = queryClient.getQueryData<{ payload?: { workspace_id?: string; network_id?: string } }>(["alerts", token, "detail", key[3]]);
          return detail?.payload?.workspace_id === workspaceId && (!networkId || detail.payload.network_id === networkId);
        }
        if (channels.has("digitalTwin") && key[1] === session.key && key[2] === session.authority) {
          if (key[0] === "intent") return key[3] === "history" || key[4] === workspaceId;
          if (key[0] === "simulation" || key[0] === "simulation-compare") return true;
        }
        return false;
      } }, { cancelRefetch: false })]).finally(() => {
        if (reconcileTimer.current !== timer) return;
        reconcileTimer.current = null;
        if (pendingChannels.current.size && isScopeCurrent()) queueReconciliation(pendingChannels.current.values().next().value!);
      });
    }, 500);
    reconcileTimer.current = timer;
  }, [isScopeCurrent, networkId, queryClient, workspaceId, session.key, session.authority]);

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
    onError: (error) => { onSocketError(error); if (error.code === "WS_BACKPRESSURE") reconcile("topology"); },
    onSubscribed: () => reconcile("topology"),
    onStatusChange: (status) => setConnectionStatus("topology", status),
    onFrame: (frame) => {
      if (isCurrent() && isTopologyFrame(frame) && frame.data?.node) {
        applyTopologyDelta(frame.data, frame.timestamp);
        reconcile("topology");
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
    onError: (error) => { onSocketError(error); if (error.code === "WS_BACKPRESSURE") reconcile("telemetry"); },
    onSubscribed: () => reconcile("telemetry"),
    onStatusChange: (status) => setConnectionStatus("telemetry", status),
    onFrame: (frame) => {
      if (isCurrent() && isTelemetryFrame(frame) && frame.data?.metric &&
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
    onError: (error) => { onSocketError(error); if (error.code === "WS_BACKPRESSURE") reconcile("alerts"); },
    onSubscribed: () => reconcile("alerts"),
    onStatusChange: (status) => setConnectionStatus("alerts", status),
    onFrame: (frame) => {
      if (isCurrent() && isAlertFrame(frame) && frame.data?.alert) {
        // Alerts has no documented subscription filter. Fail closed on unscoped payloads.
        const payload = frame.data.alert.payload;
        if (payload.workspace_id !== workspaceId || (networkId && payload.network_id !== networkId)) return;
        applyAlertDelta(frame.data, {
          correlation_id: frame.correlation_id,
          timestamp: frame.timestamp,
        });
        reconcile("alerts");
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
    onError: (error) => { onSocketError(error); if (error.code === "WS_BACKPRESSURE") reconcile("digitalTwin"); },
    onSubscribed: () => reconcile("digitalTwin"),
    onStatusChange: (status) => setConnectionStatus("digitalTwin", status),
    onFrame: (frame) => {
      if (isDigitalTwinFrame(frame) && frame.data?.scene_object) {
        if (!isCurrent() || !workspaceId || !networkId) return;
        applyDigitalTwinDelta(frame.data, frame.timestamp, { workspaceId, networkId });
        reconcile("digitalTwin");
      }
    },
  });

  return null;
}

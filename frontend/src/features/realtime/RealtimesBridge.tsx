import { useCallback, useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useManagedWebSocket } from "@/shared/realtime/useManagedWebSocket";
import { useLiveStore, type LiveDeltaBatch, type RealtimeChannel } from "@/features/realtime/store";
import { createFrameQueue, type FrameQueue } from "@/features/realtime/frameQueue";
import { patchDeviceList, patchGraph, patchNodeDetail } from "@/features/topology/graphPatch";
import type { DeviceList, TopologyGraph, TopologyNodeWithNeighbours } from "@/shared/types/network";
import { recoverSocketUpgrade, refreshSession } from "@/features/auth/session";
import { hasPermission } from "@/features/auth/permissions";
import { authorityKey, useSessionScope } from "@/features/auth/sessionScope";
import { useUiStore } from "@/shared/state/ui-store";
import { reconcileKnownScenes } from "./reconcileScenes";
import { isScopedKey, scopedKey } from "@/shared/lib/queryKeys";
import type {
  AlertDeltaData,
  DigitalTwinDeltaData,
  RealtimeHaltReason,
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

type QueuedFrame =
  | { channel: "topology"; delta: TopologyDeltaData; timestamp?: string }
  | { channel: "telemetry"; delta: TelemetryDeltaData }
  | { channel: "alerts"; delta: AlertDeltaData; context: { correlation_id?: string; timestamp?: string } }
  | { channel: "digitalTwin"; delta: DigitalTwinDeltaData; timestamp?: string; scope: { workspaceId: string; networkId: string } };

interface CachedGraph { data: TopologyGraph; nextCursor: string | null }

const activeQueues = new Set<FrameQueue<QueuedFrame>>();

/** Apply every queued realtime frame now (tests and synchronous hand-offs). */
export function flushRealtimeFrames() {
  for (const queue of activeQueues) queue.flush();
}

const SOCKET_ERROR_TOASTS: Record<string, { title: string; tone: "warn" | "danger"; quietMs: number }> = {
  WS_BACKPRESSURE: { title: "Realtime backlog detected", tone: "warn", quietMs: 30_000 },
  WS_UNAVAILABLE: { title: "Realtime temporarily unavailable", tone: "warn", quietMs: 60_000 },
  WS_SUBSCRIBE_TIMEOUT: { title: "Realtime subscription timed out", tone: "warn", quietMs: 60_000 },
  WS_UNKNOWN_CHANNEL: { title: "Realtime channel mismatch", tone: "danger", quietMs: 3_000 },
  WS_INVALID_FILTER: { title: "Realtime filter rejected", tone: "danger", quietMs: 3_000 },
  WS_FORBIDDEN: { title: "Realtime access denied", tone: "danger", quietMs: 3_000 },
  WS_MESSAGE_TOO_BIG: { title: "Realtime request rejected", tone: "danger", quietMs: 3_000 },
};

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
  const keyScope = useMemo(() => ({ key: session.key, authority: session.authority }), [session.key, session.authority]);

  const contextKey = JSON.stringify([generation, userId, organizationId, workspaceId, networkId, session.authority]);
  const epoch = useLiveStore((state) => state.epoch);
  const isScopeCurrent = useCallback(() => {
    const auth = useAuthStore.getState();
    const scope = useWorkspaceStore.getState();
    return !auth.endingSession && Boolean(auth.accessToken) && useLiveStore.getState().epoch === epoch &&
      JSON.stringify([auth.generation, auth.userId, scope.organizationId, scope.workspaceId, scope.networkId, authorityKey(auth.profile)]) === contextKey;
  }, [contextKey, epoch]);
  // Scope, not credential: a rotated token of the same session keeps its sockets (ADR-028).
  const isCurrent = isScopeCurrent;
  const retryKey = useLiveStore((state) => state.realtimeRetry);
  const haltRealtime = useLiveStore((state) => state.haltRealtime);
  const scoped = { contextKey, isCurrent, retryKey, onUpgradeFailure: recoverSocketUpgrade };
  const onHalt = (channel: RealtimeChannel) => (reason: RealtimeHaltReason, error: WebSocketErrorData) => {
    if (isScopeCurrent()) haltRealtime(channel, { reason, message: error.message });
  };
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
      // Keys are [domain, sessionKey, authority, ...params] (ADR-028): match the scope, never the token.
      const graph = queryClient.getQueryData<{ data: { nodes: { device_id: string }[] } }>(scopedKey(keyScope, "topology", networkId));
      const deviceIds = new Set(graph?.data.nodes.map((node) => node.device_id));
      const controller = new AbortController();
      sceneAbort.current = controller;
      const scenes = channels.has("digitalTwin") && token && workspaceId && networkId && hasPermission(useAuthStore.getState().profile, "read:topology")
        ? reconcileKnownScenes(token, workspaceId, networkId, isScopeCurrent, controller.signal, () => useAuthStore.getState().accessToken!) : Promise.resolve();
      void Promise.all([scenes, queryClient.invalidateQueries({ predicate: (query) => {
        const key = query.queryKey;
        if (channels.has("topology") && isScopedKey(key, keyScope)) {
          if (key[0] === "networks") return key[3] === workspaceId;
          if (key[0] === "topology" || key[0] === "devices") return key[3] === networkId;
          if (["topology-node", "topology-neighbours", "topology-impact"].includes(String(key[0]))) return deviceIds.has(String(key[3]));
        }
        if (channels.has("telemetry") && key[0] === "telemetry" && key[2] === keyScope.key && key[3] === keyScope.authority) {
          // Device reads are already tenant-bound, including devices outside a
          // partial/unmounted graph or beyond the first inventory page.
          if (key[1] === "device") return true;
          if (key[1] === "history") {
            const scope = key[4] as { networkId?: string; workspaceId?: string } | undefined;
            return (!scope?.workspaceId || scope.workspaceId === workspaceId) &&
              (scope?.networkId ? scope.networkId === networkId : scope?.workspaceId === workspaceId);
          }
        }
        if (channels.has("alerts") && isScopedKey(key, keyScope, "alerts")) {
          const options = key[3];
          if (options && typeof options === "object") {
            const scope = options as { workspaceId?: string; networkId?: string };
            return (!scope.workspaceId || scope.workspaceId === workspaceId) && (!scope.networkId || scope.networkId === networkId);
          }
          // Detail/history have only an ID in their key. Require cached owner
          // evidence rather than invalidating another network's inspected alert.
          const detail = queryClient.getQueryData<{ payload?: { workspace_id?: string; network_id?: string } }>(scopedKey(keyScope, "alerts", "detail", key[4]));
          return detail?.payload?.workspace_id === workspaceId && (!networkId || detail.payload.network_id === networkId);
        }
        if (channels.has("digitalTwin") && key[1] === keyScope.key && key[2] === keyScope.authority) {
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
  }, [isScopeCurrent, networkId, queryClient, workspaceId, keyScope]);

  const setConnectionStatus = useLiveStore((state) => state.setConnectionStatus);

  // Apply topology deltas to cached REST reads; true when only a full resync can be correct.
  const patchTopologyCaches = useCallback((deltas: TopologyDeltaData[]) => {
    const graphKey = scopedKey(keyScope, "topology", networkId);
    const cached = queryClient.getQueryData<CachedGraph>(graphKey);
    let resync = false;
    if (cached) {
      const patch = patchGraph(cached.data, deltas);
      if (patch.graph !== cached.data) queryClient.setQueryData<CachedGraph>(graphKey, { ...cached, data: patch.graph });
      // A partial crawl cannot resolve unknown nodes by re-crawling; a complete one can.
      resync = patch.structural || (patch.unresolved && cached.nextCursor === null);
    } else {
      resync = deltas.some((delta) => delta.delta_type !== "update");
    }
    queryClient.setQueriesData<DeviceList>({ queryKey: scopedKey(keyScope, "devices", networkId) }, (list) => list && patchDeviceList(list, deltas));
    for (const id of new Set(deltas.map((delta) => delta.node.device_id))) {
      queryClient.setQueryData<TopologyNodeWithNeighbours>(scopedKey(keyScope, "topology-node", id), (detail) => detail && patchNodeDetail(detail, deltas));
    }
    return resync;
  }, [keyScope, networkId, queryClient]);

  // One store update (and one render) per animation frame, however many frames arrived.
  const applyFrames = useCallback((items: QueuedFrame[], overflowed: boolean) => {
    if (!isScopeCurrent()) return;
    const batch: Required<LiveDeltaBatch> = { topology: [], telemetry: [], alerts: [], digitalTwin: [] };
    for (const item of items) {
      if (item.channel === "topology") batch.topology.push({ delta: item.delta, timestamp: item.timestamp });
      else if (item.channel === "telemetry") batch.telemetry.push(item.delta);
      else if (item.channel === "alerts") batch.alerts.push({ delta: item.delta, context: item.context });
      else batch.digitalTwin.push({ delta: item.delta, timestamp: item.timestamp, scope: item.scope });
    }
    useLiveStore.getState().applyDeltaBatch(batch);
    if (batch.topology.length && patchTopologyCaches(batch.topology.map((frame) => frame.delta))) reconcile("topology");
    // Dropped frames are a gap: resynchronize every channel from REST.
    if (overflowed) for (const channel of ["topology", "telemetry", "alerts", "digitalTwin"]) reconcile(channel);
  }, [isScopeCurrent, patchTopologyCaches, reconcile]);
  const applyFramesRef = useRef(applyFrames);
  useEffect(() => { applyFramesRef.current = applyFrames; }, [applyFrames]);
  const queue = useMemo(() => createFrameQueue<QueuedFrame>((items, overflowed) => applyFramesRef.current(items, overflowed)), []);
  useEffect(() => {
    activeQueues.add(queue);
    return () => { activeQueues.delete(queue); queue.clear(); };
  }, [queue]);
  // Frames received for a previous scope/epoch are never applied.
  useEffect(() => () => queue.clear(), [queue, contextKey, epoch]);

  const showSocketErrorToast = useCallback(
    (error: WebSocketErrorData) => {
      // Expiry is recovered silently; the connection cap has its own persistent control.
      if (error.code === "WS_UNAUTHORIZED" || error.code === "WS_CONNECTION_LIMIT") {
        return;
      }
      const presentation = SOCKET_ERROR_TOASTS[error.code] ?? { title: "Realtime channel error", tone: "danger" as const, quietMs: 3_000 };
      // Transient outages retry with backoff: one notice per quiet window, not one per attempt.
      const now = Date.now();
      const lastShownAt = lastToastByCodeRef.current[error.code] ?? 0;
      if (now - lastShownAt < presentation.quietMs) {
        return;
      }
      lastToastByCodeRef.current[error.code] = now;
      pushToast({ tone: presentation.tone, title: presentation.title, description: error.message });
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
    onHalt: onHalt("topology"),
    channel: "topology",
    filters: networkId ? { network_id: networkId } : {},
    enabled: Boolean(token && workspaceId && networkId && !endingSession && hasPermission(profile, "read:topology")),
    onUnauthorized,
    onError: (error) => { onSocketError(error); if (error.code === "WS_BACKPRESSURE") reconcile("topology"); },
    onSubscribed: () => reconcile("topology"),
    onStatusChange: (status) => setConnectionStatus("topology", status),
    onFrame: (frame) => {
      if (isCurrent() && isTopologyFrame(frame) && frame.data?.node) {
        // Patched into caches at flush; a full resync only on subscribe/backpressure/gap.
        queue.push({ channel: "topology", delta: frame.data, timestamp: frame.timestamp });
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/telemetry",
    token,
    onHalt: onHalt("telemetry"),
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
        queue.push({ channel: "telemetry", delta: frame.data });
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/alerts",
    token,
    onHalt: onHalt("alerts"),
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
        queue.push({ channel: "alerts", delta: frame.data, context: { correlation_id: frame.correlation_id, timestamp: frame.timestamp } });
        reconcile("alerts");
      }
    },
  });

  useManagedWebSocket<WebSocketEnvelope<unknown>>({
    ...scoped,
    path: "/ws/digital-twin",
    token,
    onHalt: onHalt("digitalTwin"),
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
        queue.push({ channel: "digitalTwin", delta: frame.data, timestamp: frame.timestamp, scope: { workspaceId, networkId } });
        reconcile("digitalTwin");
      }
    },
  });

  return null;
}

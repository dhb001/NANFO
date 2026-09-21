import { act, render as rtlRender, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeBridge } from "@/features/realtime/RealtimesBridge";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { WebSocketErrorData, WebSocketEnvelope } from "@/shared/types/ws";
import { operatorProfile } from "@/test/profile";
import { useLiveStore } from "@/features/realtime/store";
import * as simulationApi from "@/features/simulation/api";
import type { SimulationDetail } from "@/shared/types/simulation";
import { authorityKey } from "@/features/auth/sessionScope";

function stableScope() {
  const auth = useAuthStore.getState();
  const scope = useWorkspaceStore.getState();
  return JSON.stringify([auth.generation, auth.userId, scope.organizationId, scope.workspaceId, scope.networkId]);
}

interface CapturedSocketOptions {
  path: string;
  enabled: boolean;
  isCurrent: () => boolean;
  onFrame: (frame: WebSocketEnvelope<unknown>) => void;
  onUnauthorized?: () => void;
  onError?: (error: WebSocketErrorData) => void;
  onSubscribed?: () => void;
}

const capturedSockets: CapturedSocketOptions[] = [];
const refreshMock = vi.fn();
const getProfileMock = vi.fn();
let client: QueryClient;
function render(element: ReactElement) {
  return rtlRender(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
}

vi.mock("@/shared/realtime/useManagedWebSocket", () => ({
  useManagedWebSocket: (options: CapturedSocketOptions) => {
    capturedSockets.push(options);
  },
}));

vi.mock("@/features/auth/api", () => ({
  refresh: (...args: unknown[]) => refreshMock(...args),
  getProfile: (...args: unknown[]) => getProfileMock(...args),
}));

function getSocket(path: string) {
  const socket = capturedSockets.find((item) => item.path === path);
  if (!socket) {
    throw new Error(`Socket options not captured for ${path}`);
  }
  return socket;
}

describe("RealtimeBridge", () => {
  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    capturedSockets.length = 0;
    refreshMock.mockReset();
    getProfileMock.mockResolvedValue(operatorProfile);

    useAuthStore.setState({
      profile: operatorProfile,
      accessToken: "access-token-old",
      refreshToken: "refresh-token-1",
      userId: "00000000-0000-0000-0000-000000000123",
    });
    useWorkspaceStore.setState({
      organizationId: "00000000-0000-0000-0000-000000000111",
      workspaceId: "00000000-0000-0000-0000-000000000222",
      networkId: "00000000-0000-0000-0000-000000000333",
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });
    useLiveStore.getState().reset();
  });

  it("refreshes auth session when websocket unauthorized is reported", async () => {
    refreshMock.mockResolvedValueOnce({ access_token: "access-token-new", refresh_token: "refresh-token-new", token_type: "bearer", expires_in: 900 });
    render(<RealtimeBridge />);

    const topologySocket = getSocket("/ws/topology");
    topologySocket.onUnauthorized?.();

    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalledWith("refresh-token-1");
      expect(useAuthStore.getState().accessToken).toBe("access-token-new");
    });
    expect(useAuthStore.getState().refreshToken).toBe("refresh-token-new");
    expect(useAuthStore.getState().userId).toBe("00000000-0000-0000-0000-000000000123");
  });

  it("clears auth session if websocket unauthorized refresh fails", async () => {
    refreshMock.mockRejectedValueOnce(new Error("refresh failed"));
    render(<RealtimeBridge />);

    const topologySocket = getSocket("/ws/topology");
    topologySocket.onUnauthorized?.();

    await waitFor(() => {
      expect(useAuthStore.getState().accessToken).toBeNull();
      expect(useAuthStore.getState().refreshToken).toBeNull();
      expect(useAuthStore.getState().userId).toBeNull();
    });
  });

  it("shows throttled toast feedback for non-unauthorized websocket errors", () => {
    render(<RealtimeBridge />);

    const telemetrySocket = getSocket("/ws/telemetry");
    telemetrySocket.onError?.({ code: "WS_BACKPRESSURE", message: "Delta queue exceeded" });
    telemetrySocket.onError?.({ code: "WS_BACKPRESSURE", message: "Delta queue exceeded" });
    telemetrySocket.onError?.({ code: "WS_UNAUTHORIZED", message: "token expired" });

    const toasts = useUiStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({
      tone: "warn",
      title: "Realtime backlog detected",
      description: "Delta queue exceeded",
    });
  });

  it("drops telemetry and alerts outside the selected scope", () => {
    render(<RealtimeBridge />);
    const workspaceId = useWorkspaceStore.getState().workspaceId;
    const networkId = useWorkspaceStore.getState().networkId;
    const telemetry = getSocket("/ws/telemetry");
    const alerts = getSocket("/ws/alerts");
    const metric = { device_id: "device", metric: "cpu", workspace_id: workspaceId, network_id: networkId, value: 45, observed_at: "2026-09-10T00:00:00Z", source: "plugin", unit: "%", tags: {} };
    act(() => {
      telemetry.onFrame({ event: "telemetry.received", data: { metric: { ...metric, network_id: "other" } } });
      alerts.onFrame({ event: "alert.created", data: { alert: { event_id: "unscoped", payload: {} } } });
    });
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toEqual([]);
    expect(useLiveStore.getState().alerts).toEqual([]);
    act(() => {
      telemetry.onFrame({ event: "telemetry.received", data: { metric } });
      alerts.onFrame({ event: "alert.created", data: { alert: { event_id: "scoped", payload: { workspace_id: workspaceId, network_id: networkId } } } });
    });
    expect(Object.values(useLiveStore.getState().telemetryByDeviceMetric)).toEqual([metric]);
    expect(useLiveStore.getState().alerts).toHaveLength(1);
    act(() => useWorkspaceStore.getState().setNetworkId("other"));
    expect(telemetry.isCurrent()).toBe(false);
    expect(alerts.isCurrent()).toBe(false);
    expect(useLiveStore.getState().alerts).toEqual([]);
  });

  it("does not subscribe channels denied by the current profile", () => {
    useAuthStore.getState().setProfile({ ...operatorProfile, permissions: [] });
    render(<RealtimeBridge />);
    expect(capturedSockets.every((socket) => !socket.enabled)).toBe(true);
  });

  it("rejects telemetry callbacks from old epochs, tokens and scopes and isolates malformed frames", () => {
    const { unmount } = render(<RealtimeBridge />);
    const old = getSocket("/ws/telemetry");
    const metric = { event_id: "m", device_id: "d", metric: "cpu", workspace_id: useWorkspaceStore.getState().workspaceId, network_id: useWorkspaceStore.getState().networkId, value: 42, observed_at: "2026-09-19T00:00:00Z", source: "plugin", unit: "%", tags: {} };
    const frame = { event: "telemetry.received", data: { metric } };
    act(() => {
      old.onFrame({ event: "telemetry.received", data: null });
      old.onFrame({ event: "telemetry.received", data: { metric: { ...metric, value: "bad" } } });
      old.onFrame(frame);
    });
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toHaveLength(1);
    act(() => useLiveStore.getState().reset());
    act(() => old.onFrame(frame));
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toEqual([]);
    const fresh = capturedSockets.filter((item) => item.path === "/ws/telemetry").at(-1)!;
    act(() => useAuthStore.setState({ accessToken: "rotated" }));
    act(() => fresh.onFrame(frame));
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toEqual([]);
    const rotated = capturedSockets.filter((item) => item.path === "/ws/telemetry").at(-1)!;
    act(() => useWorkspaceStore.getState().setNetworkId("other"));
    act(() => rotated.onFrame(frame));
    expect(useLiveStore.getState().telemetryKeysNewestFirst).toEqual([]);
    unmount();
  });

  it("coalesces subscribed and backpressure reconciliation and excludes other tokens/networks", () => {
    vi.useFakeTimers();
    const token = useAuthStore.getState().accessToken;
    const scope = useWorkspaceStore.getState();
    const selected = ["topology", token, scope.networkId];
    const other = ["topology", token, "other"];
    const history = ["telemetry", "history", stableScope(), authorityKey(), { networkId: scope.networkId }];
    const otherHistory = ["telemetry", "history", stableScope(), authorityKey(), { networkId: "other" }];
    const intent = ["intent", stableScope(), authorityKey(), "i", scope.workspaceId];
    for (const key of [selected, other, history, otherHistory, intent, ["alerts", token, {}]]) client.setQueryData(key, { data: { nodes: [] } });
    const invalidation = vi.spyOn(client, "invalidateQueries");
    const { unmount } = render(<RealtimeBridge />);
    act(() => {
      for (let i = 0; i < 20; i++) for (const path of ["/ws/topology", "/ws/telemetry", "/ws/digital-twin", "/ws/alerts"]) {
        getSocket(path).onSubscribed?.();
        getSocket(path).onError?.({ code: "WS_BACKPRESSURE", message: "Backlog" });
      }
      vi.advanceTimersByTime(500);
    });
    expect(invalidation).toHaveBeenCalledTimes(1);
    expect(client.getQueryState(selected)?.isInvalidated).toBe(true);
    expect(client.getQueryState(history)?.isInvalidated).toBe(true);
    expect(client.getQueryState(intent)?.isInvalidated).toBe(true);
    expect(client.getQueryState(other)?.isInvalidated).toBe(false);
    expect(client.getQueryState(otherHistory)?.isInvalidated).toBe(false);
    act(() => { getSocket("/ws/topology").onSubscribed?.(); useWorkspaceStore.getState().setNetworkId("other"); });
    act(() => vi.advanceTimersByTime(1000));
    expect(invalidation).toHaveBeenCalledTimes(1);
    unmount();
    vi.useRealTimers();
  });

  it("reconciles active simulation detail and comparison and queues at most one follow-up while REST is pending", async () => {
    vi.useFakeTimers();
    let finish!: (value: unknown) => void;
    const fetchDetail = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; })).mockResolvedValue({ status: "completed" });
    const detail = new QueryObserver(client, { queryKey: ["simulation", stableScope(), authorityKey(), "sim"], queryFn: fetchDetail, initialData: { status: "queued" }, staleTime: Infinity });
    const compare = new QueryObserver(client, { queryKey: ["simulation-compare", stableScope(), authorityKey(), "sim", "base"], queryFn: vi.fn().mockResolvedValue({}), initialData: {}, staleTime: Infinity });
    const unsubscribeDetail = detail.subscribe(() => undefined);
    const unsubscribeCompare = compare.subscribe(() => undefined);
    const invalidation = vi.spyOn(client, "invalidateQueries");
    const { unmount } = render(<RealtimeBridge />);
    await act(async () => { getSocket("/ws/digital-twin").onSubscribed?.(); await vi.advanceTimersByTimeAsync(500); });
    expect(fetchDetail).toHaveBeenCalledTimes(1);
    await act(async () => {
      for (let index = 0; index < 100; index++) getSocket("/ws/digital-twin").onError?.({ code: "WS_BACKPRESSURE", message: "Backlog" });
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(invalidation).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ status: "completed" }); await vi.advanceTimersByTimeAsync(500); });
    expect(invalidation).toHaveBeenCalledTimes(2);
    expect(fetchDetail).toHaveBeenCalledTimes(2);
    unsubscribeDetail(); unsubscribeCompare(); unmount();
    vi.useRealTimers();
  });
  it("reconciles known overlay on subscribed/backpressure with no mounted detail query", async () => {
    vi.useFakeTimers();
    const simulationId = "00000000-0000-0000-0000-000000000701";
    const scope = useWorkspaceStore.getState();
    const fetch = vi.spyOn(simulationApi, "getSimulationDetail").mockResolvedValue({ success: true, meta: { request_id: "test", timestamp: "2026-09-10T00:01:00Z" }, errors: null, data: {
      simulation_id: simulationId, network_id: scope.networkId!, workspace_id: scope.workspaceId!, status: "paused", state: "paused", revision: 2, updated_at: "2026-09-10T00:01:00Z",
    } as SimulationDetail });
    const { unmount } = render(<RealtimeBridge />);
    act(() => getSocket("/ws/digital-twin").onFrame({ event: "simulation.started", timestamp: "2026-09-10T00:00:00Z", data: {
      delta_type: "update", scene_object: { id: "legacy", object_type: "simulation_state", simulation_id: simulationId, status: "running" },
    } }));
    await act(async () => { getSocket("/ws/digital-twin").onSubscribed?.(); await vi.advanceTimersByTimeAsync(500); });
    expect(client.getQueryCache().getAll()).toHaveLength(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(useLiveStore.getState().sceneObjects[`simulation:${simulationId}`].status).toBe("paused");
    await act(async () => { getSocket("/ws/digital-twin").onError?.({ code: "WS_BACKPRESSURE", message: "backlog" }); await vi.advanceTimersByTimeAsync(500); });
    expect(fetch).toHaveBeenCalledTimes(2);
    unmount(); fetch.mockRestore(); vi.useRealTimers();
  });
});

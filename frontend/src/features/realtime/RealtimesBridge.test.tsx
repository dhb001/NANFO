import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeBridge } from "@/features/realtime/RealtimesBridge";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { WebSocketErrorData, WebSocketEnvelope } from "@/shared/types/ws";
import { operatorProfile } from "@/test/profile";
import { useLiveStore } from "@/features/realtime/store";

interface CapturedSocketOptions {
  path: string;
  enabled: boolean;
  isCurrent: () => boolean;
  onFrame: (frame: WebSocketEnvelope<unknown>) => void;
  onUnauthorized?: () => void;
  onError?: (error: WebSocketErrorData) => void;
}

const capturedSockets: CapturedSocketOptions[] = [];
const refreshMock = vi.fn();
const getProfileMock = vi.fn();

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
    const metric = { device_id: "device", metric: "cpu", workspace_id: workspaceId, network_id: networkId };
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
});

import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeBridge } from "@/features/realtime/RealtimesBridge";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { WebSocketErrorData } from "@/shared/types/ws";

interface CapturedSocketOptions {
  path: string;
  onUnauthorized?: () => void;
  onError?: (error: WebSocketErrorData) => void;
}

const capturedSockets: CapturedSocketOptions[] = [];
const refreshMock = vi.fn();

vi.mock("@/shared/realtime/useManagedWebSocket", () => ({
  useManagedWebSocket: (options: CapturedSocketOptions) => {
    capturedSockets.push(options);
  },
}));

vi.mock("@/features/auth/api", () => ({
  refresh: (...args: unknown[]) => refreshMock(...args),
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

    useAuthStore.setState({
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
  });

  it("refreshes auth session when websocket unauthorized is reported", async () => {
    refreshMock.mockResolvedValueOnce({ access_token: "access-token-new", expires_in: 900 });
    render(<RealtimeBridge />);

    const topologySocket = getSocket("/ws/topology");
    topologySocket.onUnauthorized?.();

    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalledWith("refresh-token-1");
      expect(useAuthStore.getState().accessToken).toBe("access-token-new");
    });
    expect(useAuthStore.getState().refreshToken).toBe("refresh-token-1");
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
});

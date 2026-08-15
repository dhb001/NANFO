import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useManagedWebSocket } from "@/shared/realtime/useManagedWebSocket";

interface TestFrame {
  event: string;
  data?: Record<string, unknown>;
}

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  readonly url: string;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.onclose?.(new CloseEvent("close"));
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  static reset() {
    MockWebSocket.instances = [];
  }
}

interface HarnessProps {
  onFrame: (frame: TestFrame) => void;
  onUnauthorized: () => void;
  onError: (error: { code: string; message: string }) => void;
}

function Harness({ onFrame, onUnauthorized, onError }: HarnessProps) {
  useManagedWebSocket<TestFrame>({
    path: "/ws/telemetry",
    token: "token-1",
    channel: "telemetry",
    filters: { network_id: "network-1" },
    enabled: true,
    onFrame,
    onUnauthorized,
    onError,
  });
  return null;
}

describe("useManagedWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.reset();
    vi.clearAllMocks();
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  });

  it("subscribes on open and routes frames/errors correctly", () => {
    const onFrame = vi.fn();
    const onUnauthorized = vi.fn();
    const onError = vi.fn();

    render(<Harness onFrame={onFrame} onUnauthorized={onUnauthorized} onError={onError} />);

    const socket = MockWebSocket.instances[0];
    expect(socket).toBeDefined();
    expect(socket.url).toContain("/ws/telemetry?token=token-1");

    act(() => {
      socket.onopen?.(new Event("open"));
    });
    expect(socket.send).toHaveBeenCalledWith(
      JSON.stringify({ action: "subscribe", channel: "telemetry", filters: { network_id: "network-1" } }),
    );

    act(() => {
      socket.onmessage?.({
        data: JSON.stringify({ event: "telemetry.received", data: { value: 42 } }),
      } as MessageEvent);
    });
    expect(onFrame).toHaveBeenCalledWith({ event: "telemetry.received", data: { value: 42 } });

    act(() => {
      socket.onmessage?.({
        data: JSON.stringify({ event: "error", data: { code: "WS_BACKPRESSURE", message: "Queue full" } }),
      } as MessageEvent);
    });
    expect(onError).toHaveBeenCalledWith({ code: "WS_BACKPRESSURE", message: "Queue full" });
    expect(onFrame).toHaveBeenCalledTimes(1);

    act(() => {
      socket.onmessage?.({
        data: JSON.stringify({ event: "error", data: { code: "WS_UNAUTHORIZED", message: "Expired token" } }),
      } as MessageEvent);
    });
    expect(onError).toHaveBeenCalledWith({ code: "WS_UNAUTHORIZED", message: "Expired token" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(socket.close).toHaveBeenCalled();
  });

  it("normalizes malformed websocket error frames", () => {
    const onFrame = vi.fn();
    const onUnauthorized = vi.fn();
    const onError = vi.fn();

    render(<Harness onFrame={onFrame} onUnauthorized={onUnauthorized} onError={onError} />);

    const socket = MockWebSocket.instances[0];
    act(() => {
      socket.onmessage?.({ data: JSON.stringify({ event: "error" }) } as MessageEvent);
    });

    expect(onError).toHaveBeenCalledWith({
      code: "WS_ERROR",
      message: "WebSocket error frame missing payload.",
    });
    expect(onFrame).not.toHaveBeenCalled();
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

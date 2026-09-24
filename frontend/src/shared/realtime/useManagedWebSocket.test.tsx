import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RECONNECT_BACKOFF, useManagedWebSocket, WS_BEARER_PREFIX, WS_PROTOCOL } from "@/shared/realtime/useManagedWebSocket";
import type { SocketUpgradeRecovery } from "@/shared/types/ws";
import { recoverSocketUpgrade } from "@/features/auth/session";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";

interface TestFrame {
  event: string;
  data?: Record<string, unknown>;
}

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readonly protocols: string[];
  protocol = "";
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void | Promise<void>) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    void this.onclose?.(new CloseEvent("close"));
  });

  constructor(url: string, protocols: string | string[] = []) {
    this.url = url;
    this.protocols = Array.isArray(protocols) ? protocols : [protocols];
    MockWebSocket.instances.push(this);
  }

  static reset() {
    MockWebSocket.instances = [];
  }
}

const last = () => MockWebSocket.instances.at(-1)!;
const frame = (socket: MockWebSocket, payload: unknown) =>
  socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) }));
const serverError = (socket: MockWebSocket, code: string, message = code) => frame(socket, { event: "error", data: { code, message } });
const closeWith = (socket: MockWebSocket, code: number) => socket.onclose?.(new CloseEvent("close", { code }));

function acknowledge(socket: MockWebSocket, filters: Record<string, unknown> = {}) {
  socket.protocol = WS_PROTOCOL;
  socket.onopen?.(new Event("open"));
  frame(socket, { event: "subscribed", channel: "telemetry", filters });
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
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("authenticates with the nanfo.v1 bearer subprotocol and never puts the token in the URL (C1)", () => {
    render(<Harness onFrame={vi.fn()} onUnauthorized={vi.fn()} onError={vi.fn()} />);
    const socket = MockWebSocket.instances[0];
    expect(socket.protocols).toEqual([WS_PROTOCOL, `${WS_BEARER_PREFIX}token-1`]);
    expect(socket.protocols).toEqual(["nanfo.v1", "nanfo.bearer.token-1"]);
    const url = new URL(socket.url);
    expect(url.search).toBe("");
    expect(socket.url).not.toContain("token");
    // Same-origin default (C16): derived from the page origin.
    expect(`${url.protocol}//${url.host}${url.pathname}`).toBe(`ws://${window.location.host}/ws/telemetry`);
  });

  it("requires the matching subscribed ACK before readiness or data, and bounds unauthorized rotation", () => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    const onSubscribed = vi.fn();
    const onStatusChange = vi.fn();
    const onUnauthorized = vi.fn();
    const { rerender } = renderHook(({ token }) => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token, channel: "telemetry", filters: { network_id: "n" }, enabled: true,
      onFrame, onSubscribed, onStatusChange, onUnauthorized,
    }), { initialProps: { token: "first" } });
    const socket = MockWebSocket.instances[0];
    act(() => {
      socket.onopen?.(new Event("open"));
      frame(socket, { event: "telemetry.received" });
      frame(socket, { event: "subscribed", channel: "telemetry", filters: { network_id: "wrong" } });
    });
    expect(onStatusChange).not.toHaveBeenCalledWith("open");
    expect(onFrame).not.toHaveBeenCalled();
    act(() => acknowledge(socket, { network_id: "n" }));
    expect(onStatusChange).toHaveBeenLastCalledWith("open");
    expect(onSubscribed).toHaveBeenCalledTimes(1);
    act(() => { void closeWith(socket, 1008); });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    // The refreshed credential resumes the parked channel; a second rejection does not refresh again.
    rerender({ token: "rotated" });
    act(() => { vi.advanceTimersByTime(0); });
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(last().protocols[1]).toBe("nanfo.bearer.rotated");
    act(() => {
      last().onopen?.(new Event("open"));
      void closeWith(last(), 1008);
      vi.advanceTimersByTime(120_000);
    });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect a healthy subscribed socket when the access token rotates", () => {
    vi.useFakeTimers();
    const onSubscribed = vi.fn();
    const { rerender, unmount } = renderHook(({ token }) => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token, channel: "telemetry", enabled: true, onFrame: vi.fn(), onSubscribed,
    }), { initialProps: { token: "first" } });
    act(() => acknowledge(MockWebSocket.instances[0]));
    rerender({ token: "second" });
    rerender({ token: "third" });
    act(() => { vi.advanceTimersByTime(120_000); });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].close).not.toHaveBeenCalled();
    expect(onSubscribed).toHaveBeenCalledTimes(1);
    unmount();
  });

  it("reconnects with the already-rotated credential on expiry without another refresh", () => {
    vi.useFakeTimers();
    const onUnauthorized = vi.fn();
    const { rerender, unmount } = renderHook(({ token }) => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token, channel: "telemetry", enabled: true, onFrame: vi.fn(), onUnauthorized,
    }), { initialProps: { token: "first" } });
    act(() => acknowledge(MockWebSocket.instances[0]));
    rerender({ token: "second" });
    act(() => { serverError(MockWebSocket.instances[0], "WS_UNAUTHORIZED", "Token expired."); });
    act(() => { vi.advanceTimersByTime(0); });
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(last().protocols).toEqual(["nanfo.v1", "nanfo.bearer.second"]);
    unmount();
  });

  it("times out missing acknowledgments without falsely opening or refreshing auth", () => {
    vi.useFakeTimers();
    const onStatusChange = vi.fn();
    const onUnauthorized = vi.fn();
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({ path: "/ws/telemetry", token: "t", channel: "telemetry", enabled: true, onFrame: vi.fn(), onStatusChange, onUnauthorized }));
    act(() => { MockWebSocket.instances[0].onopen?.(new Event("open")); vi.advanceTimersByTime(10_000); });
    expect(MockWebSocket.instances[0].close).toHaveBeenCalledOnce();
    expect(onStatusChange).not.toHaveBeenCalledWith("open");
    expect(onUnauthorized).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(RECONNECT_BACKOFF.baseMs); });
    expect(MockWebSocket.instances).toHaveLength(2);
    unmount();
  });

  it("subscribes on open and routes frames/errors correctly", () => {
    const onFrame = vi.fn();
    const onUnauthorized = vi.fn();
    const onError = vi.fn();

    render(<Harness onFrame={onFrame} onUnauthorized={onUnauthorized} onError={onError} />);

    const socket = MockWebSocket.instances[0];
    expect(socket).toBeDefined();
    expect(socket.url).toMatch(/\/ws\/telemetry$/);

    act(() => {
      socket.onopen?.(new Event("open"));
    });
    expect(socket.send).toHaveBeenCalledWith(
      JSON.stringify({ action: "subscribe", channel: "telemetry", filters: { network_id: "network-1" } }),
    );
    act(() => { frame(socket, { event: "subscribed", channel: "telemetry", filters: { network_id: "network-1" } }); });

    act(() => { frame(socket, { event: "telemetry.received", data: { value: 42 } }); });
    expect(onFrame).toHaveBeenCalledWith({ event: "telemetry.received", data: { value: 42 } });

    act(() => { serverError(socket, "WS_BACKPRESSURE", "Queue full"); });
    expect(onError).toHaveBeenCalledWith({ code: "WS_BACKPRESSURE", message: "Queue full" });
    expect(onFrame).toHaveBeenCalledTimes(1);

    act(() => { serverError(socket, "WS_UNAUTHORIZED", "Expired token"); });
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
    act(() => { frame(socket, { event: "error" }); });

    expect(onError).toHaveBeenCalledWith({
      code: "WS_ERROR",
      message: "WebSocket error frame missing payload.",
    });
    expect(onFrame).not.toHaveBeenCalled();
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("treats a bare policy close as credential expiry and does not reconnect", () => {
    vi.useFakeTimers();
    const onUnauthorized = vi.fn();
    const onError = vi.fn();
    const { unmount } = render(<Harness onFrame={vi.fn()} onUnauthorized={onUnauthorized} onError={onError} />);
    act(() => { void closeWith(MockWebSocket.instances[0], 1008); vi.advanceTimersByTime(120_000); });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(1);
    unmount();
  });

  it("ignores all late callbacks from an old socket after context switching", () => {
    const onFrame = vi.fn();
    const onUnauthorized = vi.fn();
    const onStatusChange = vi.fn();
    const { rerender } = renderHook(({ context }) => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "token", channel: "telemetry", enabled: true,
      filters: { network_id: context }, contextKey: context, onFrame, onUnauthorized, onStatusChange,
    }), { initialProps: { context: "old" } });
    const old = MockWebSocket.instances[0];
    rerender({ context: "new" });
    onStatusChange.mockClear();
    act(() => {
      old.onopen?.(new Event("open"));
      frame(old, { event: "telemetry.received" });
      void closeWith(old, 1008);
    });
    expect(old.send).not.toHaveBeenCalled();
    expect(onFrame).not.toHaveBeenCalled();
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(onStatusChange).not.toHaveBeenCalled();
    act(() => {
      acknowledge(MockWebSocket.instances[1], { network_id: "new" });
      frame(MockWebSocket.instances[1], { event: "telemetry.received" });
    });
    expect(onFrame).toHaveBeenCalledTimes(1);
  });

  it.each(["WS_INVALID_FILTER", "WS_UNKNOWN_CHANNEL", "WS_FORBIDDEN"])("stops %s denials without refreshing or reconnecting", (code) => {
    vi.useFakeTimers();
    const onUnauthorized = vi.fn();
    const onError = vi.fn();
    const onHalt = vi.fn();
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "t", channel: "telemetry", enabled: true, onFrame: vi.fn(), onUnauthorized, onError, onHalt,
    }));
    act(() => {
      serverError(MockWebSocket.instances[0], code, "Denied");
      void closeWith(MockWebSocket.instances[0], 1008);
      vi.advanceTimersByTime(120_000);
    });
    expect(onError).toHaveBeenCalledWith({ code, message: "Denied" });
    expect(onHalt).toHaveBeenCalledWith("denied", { code, message: "Denied" });
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(1);
    unmount();
  });

  it.each([
    ["WS_UNAVAILABLE", 1013],
    ["WS_SUBSCRIBE_TIMEOUT", 1013],
    ["WS_BACKPRESSURE", 1013],
    ["WS_UNAVAILABLE", 1011],
  ])("retries transient %s (close %i) with full-jitter backoff, never as auth or filter failure", (code, closeCode) => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const onUnauthorized = vi.fn();
    const onHalt = vi.fn();
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "t", channel: "telemetry", enabled: true, onFrame: vi.fn(), onUnauthorized, onHalt,
    }));
    // Attempt n waits random() * min(cap, base * 2^(n-1)): 250, 500, 1000, ... capped at 15000 here.
    const expected = [250, 500, 1_000, 2_000, 4_000, 8_000, 15_000, 15_000];
    for (const [index, delay] of expected.entries()) {
      act(() => {
        MockWebSocket.instances[index].onopen?.(new Event("open"));
        serverError(MockWebSocket.instances[index], code);
        void closeWith(MockWebSocket.instances[index], closeCode);
      });
      act(() => { vi.advanceTimersByTime(delay - 1); });
      expect(MockWebSocket.instances).toHaveLength(index + 1);
      act(() => { vi.advanceTimersByTime(1); });
      expect(MockWebSocket.instances).toHaveLength(index + 2);
    }
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(onHalt).not.toHaveBeenCalled();
    unmount();
  });

  it("spreads reconnects across the whole jitter window and restarts the schedule after a subscription", () => {
    vi.useFakeTimers();
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "t", channel: "telemetry", enabled: true, onFrame: vi.fn(),
    }));
    act(() => { void closeWith(MockWebSocket.instances[0], 1011); vi.advanceTimersByTime(0); });
    expect(MockWebSocket.instances).toHaveLength(2);
    random.mockReturnValue(0.999);
    // Attempt 2 window is [0, 1000): 0.999 lands at 999 ms.
    act(() => { void closeWith(MockWebSocket.instances[1], 1011); vi.advanceTimersByTime(998); });
    expect(MockWebSocket.instances).toHaveLength(2);
    act(() => { vi.advanceTimersByTime(1); });
    expect(MockWebSocket.instances).toHaveLength(3);
    act(() => acknowledge(MockWebSocket.instances[2]));
    act(() => { void closeWith(MockWebSocket.instances[2], 1006); vi.advanceTimersByTime(499); });
    expect(MockWebSocket.instances).toHaveLength(4);
    unmount();
  });

  it("stops on 1009 as a terminal client error", () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    const onHalt = vi.fn();
    const onUnauthorized = vi.fn();
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "t", channel: "telemetry", enabled: true, onFrame: vi.fn(), onError, onHalt, onUnauthorized,
    }));
    act(() => { void closeWith(MockWebSocket.instances[0], 1009); vi.advanceTimersByTime(120_000); });
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: "WS_MESSAGE_TOO_BIG" }));
    expect(onHalt).toHaveBeenCalledWith("client_error", expect.objectContaining({ code: "WS_MESSAGE_TOO_BIG" }));
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(1);
    unmount();
  });

  it("stops at WS_CONNECTION_LIMIT until the retry control changes retryKey", () => {
    vi.useFakeTimers();
    const onHalt = vi.fn();
    const onUnauthorized = vi.fn();
    const { rerender, unmount } = renderHook(({ retryKey }) => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "t", channel: "telemetry", enabled: true, onFrame: vi.fn(), onHalt, onUnauthorized, retryKey,
    }), { initialProps: { retryKey: 0 } });
    act(() => {
      MockWebSocket.instances[0].onopen?.(new Event("open"));
      serverError(MockWebSocket.instances[0], "WS_CONNECTION_LIMIT", "Too many concurrent realtime connections.");
      void closeWith(MockWebSocket.instances[0], 1008);
      vi.advanceTimersByTime(120_000);
    });
    expect(onHalt).toHaveBeenCalledWith("connection_limit", { code: "WS_CONNECTION_LIMIT", message: "Too many concurrent realtime connections." });
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(1);
    rerender({ retryKey: 1 });
    expect(MockWebSocket.instances).toHaveLength(2);
    unmount();
  });

  it("halts instead of looping when the browser rejects the subprotocol list", () => {
    vi.useFakeTimers();
    const onHalt = vi.fn();
    vi.stubGlobal("WebSocket", class { constructor() { throw new DOMException("bad protocol", "SyntaxError"); } });
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "not a token", channel: "telemetry", enabled: true, onFrame: vi.fn(), onHalt,
    }));
    act(() => { vi.advanceTimersByTime(120_000); });
    expect(onHalt).toHaveBeenCalledTimes(1);
    expect(onHalt).toHaveBeenCalledWith("client_error", expect.objectContaining({ code: "WS_CLIENT_ERROR" }));
    unmount();
  });

  it("isolates malformed messages and consumer failures and reconnects after a transport disconnect", () => {
    vi.useFakeTimers();
    const onFrame = vi.fn().mockImplementationOnce(() => { throw new Error("consumer bug"); });
    const { unmount } = render(<Harness onFrame={onFrame} onUnauthorized={vi.fn()} onError={vi.fn()} />);
    act(() => {
      const socket = MockWebSocket.instances[0];
      acknowledge(socket, { network_id: "network-1" });
      socket.onmessage?.(new MessageEvent("message", { data: "invalid-json" }));
      frame(socket, { event: "telemetry.received" });
      frame(socket, { event: "telemetry.received" });
      void closeWith(socket, 1006);
      vi.advanceTimersByTime(60_000);
    });
    expect(onFrame).toHaveBeenCalledTimes(2);
    expect(MockWebSocket.instances).toHaveLength(2);
    unmount();
  });

  it("bounds pre-upgrade 1006 auth recovery across reconnects and token rotation", async () => {
    vi.useFakeTimers();
    const onUpgradeFailure = vi.fn().mockResolvedValue("conclusive");
    const { rerender, unmount } = renderHook(({ token }) => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token, channel: "telemetry", enabled: true, onFrame: vi.fn(), onUpgradeFailure,
    }), { initialProps: { token: "old" } });
    await act(async () => {
      await closeWith(MockWebSocket.instances[0], 1006);
    });
    expect(onUpgradeFailure).toHaveBeenCalledWith("old");
    rerender({ token: "fresh" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
      await closeWith(last(), 1006);
      await vi.advanceTimersByTimeAsync(60_000);
      await closeWith(last(), 1006);
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(onUpgradeFailure).toHaveBeenCalledTimes(1);
    expect(last().protocols[1]).toBe("nanfo.bearer.fresh");
    act(() => acknowledge(last()));
    await act(async () => {
      await closeWith(last(), 1006);
      await vi.advanceTimersByTimeAsync(60_000);
      await closeWith(last(), 1006);
    });
    expect(onUpgradeFailure).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("ignores a late upgrade probe completion after unmount", async () => {
    vi.useFakeTimers();
    let resolve!: (result: SocketUpgradeRecovery) => void;
    const onUpgradeFailure = vi.fn(() => new Promise<SocketUpgradeRecovery>((done) => { resolve = done; }));
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "old", channel: "telemetry", enabled: true, onFrame: vi.fn(), onUpgradeFailure,
    }));
    act(() => { void closeWith(MockWebSocket.instances[0], 1006); });
    unmount();
    await act(async () => { resolve("inconclusive"); await vi.advanceTimersByTimeAsync(60_000); });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("recovers after an outage probe fails and the access token expires offline", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    useAuthStore.getState().setSession({ accessToken: "expired", refreshToken: "refresh-old",
      userId: operatorProfile.user_id, profile: operatorProfile });
    const envelope = (data: unknown) => Response.json({ success: true, data, meta: {}, errors: null });
    const fetchMock = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("Backend offline"))
      .mockResolvedValueOnce(Response.json({ success: false, data: null, meta: {}, errors: { code: "UNAUTHORIZED", message: "Expired while offline" } }, { status: 401 }))
      .mockResolvedValueOnce(envelope({ access_token: "fresh", refresh_token: "refresh-new", token_type: "bearer", expires_in: 900 }))
      .mockResolvedValueOnce(envelope(operatorProfile));
    vi.stubGlobal("fetch", fetchMock);
    const onFrame = vi.fn();
    const { unmount } = renderHook(() => {
      const token = useAuthStore((state) => state.accessToken);
      useManagedWebSocket<TestFrame>({ path: "/ws/telemetry", token, channel: "telemetry", enabled: true,
        onFrame, onUpgradeFailure: recoverSocketUpgrade });
    });

    await act(async () => {
      await closeWith(MockWebSocket.instances[0], 1006);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().accessToken).toBe("expired");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
      await closeWith(last(), 1006);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // No unrelated REST activity: the next eligible socket failure probes the restored backend.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
      await closeWith(last(), 1006);
    });
    expect(useAuthStore.getState().accessToken).toBe("fresh");
    expect(useAuthStore.getState().refreshToken).toBe("refresh-new");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(last().protocols).toEqual(["nanfo.v1", "nanfo.bearer.fresh"]);

    // A rejected upgrade even with the fresh token must not create a rotation loop.
    await act(async () => {
      await closeWith(last(), 1006);
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
    act(() => {
      acknowledge(last());
      frame(last(), { event: "telemetry.received" });
    });
    expect(onFrame).toHaveBeenCalledWith({ event: "telemetry.received" });
    unmount();
    useAuthStore.getState().clearSession();
    vi.unstubAllGlobals();
  });

  it("backs off repeated inconclusive probes without probing every reconnect", async () => {
    vi.useFakeTimers();
    // Zero jitter isolates the probe cooldown from the transport reconnect delay.
    vi.spyOn(Math, "random").mockReturnValue(0);
    const onUpgradeFailure = vi.fn().mockResolvedValue("inconclusive");
    const { unmount } = renderHook(() => useManagedWebSocket<TestFrame>({
      path: "/ws/telemetry", token: "old", channel: "telemetry", enabled: true, onFrame: vi.fn(), onUpgradeFailure,
    }));
    await act(async () => {
      await closeWith(MockWebSocket.instances[0], 1006);
    });
    for (const expectedCalls of [2, 3, 4, 5, 6]) {
      const cooldown = Math.min(5_000 * 2 ** (expectedCalls - 2), 60_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(cooldown);
        await closeWith(last(), 1006);
      });
      expect(onUpgradeFailure).toHaveBeenCalledTimes(expectedCalls);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
        await closeWith(last(), 1006);
      });
      expect(onUpgradeFailure).toHaveBeenCalledTimes(expectedCalls);
    }
    unmount();
  });
});

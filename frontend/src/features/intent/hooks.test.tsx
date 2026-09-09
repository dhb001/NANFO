import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useExecuteIntent, useIntentDetail } from "@/features/intent/hooks";
import { executeIntent, getIntentDetail } from "@/features/intent/api";
import { useLiveStore } from "@/features/realtime/store";
import { ApiClientError } from "@/shared/lib/errors";

vi.mock("@/features/intent/api", () => ({ getIntentDetail: vi.fn(), executeIntent: vi.fn(), validateIntent: vi.fn() }));

describe("intent detail recovery", () => {
  let client: QueryClient;
  const getDetail = vi.mocked(getIntentDetail);
  const response = (status: string) => ({ success: true, data: { status }, meta: {}, errors: null }) as unknown as Awaited<ReturnType<typeof getIntentDetail>>;
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  async function advance(ms: number) {
    await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    useLiveStore.setState({ digitalTwinStatus: "closed" });
    getDetail.mockResolvedValue(response("execution_started"));
  });
  afterEach(() => { cleanup(); client.clear(); vi.useRealTimers(); });

  it("polls with backoff despite a lost socket and transient HTTP failure, stopping at terminal readback", async () => {
    getDetail.mockRejectedValueOnce(new Error("Lost response"));
    const { result } = renderHook(() => ({ ...useIntentDetail("token", "intent", "workspace") }), { wrapper });
    await advance(1);
    expect(getDetail).toHaveBeenCalledTimes(1);
    await advance(2_010);
    expect(getDetail).toHaveBeenCalledTimes(2);
    expect(result.current.data?.status).toBe("execution_started");
    getDetail.mockResolvedValue(response("execution_completed"));
    await advance(4_010);
    expect(getDetail).toHaveBeenCalledTimes(3);
    expect(result.current.data?.status).toBe("execution_completed");
    await advance(60_000);
    expect(getDetail).toHaveBeenCalledTimes(3);
  });

  it("bounds polling and still reconciles on reconnect or explicit refresh", async () => {
    const { result } = renderHook(() => ({ ...useIntentDetail("token", "intent", "workspace") }), { wrapper });
    await advance(1);
    for (let index = 0; index < 45; index += 1) await advance(15_100);
    expect(getDetail).toHaveBeenCalledTimes(40);
    act(() => useLiveStore.setState({ digitalTwinStatus: "connecting" }));
    getDetail.mockResolvedValue(response("execution_failed"));
    act(() => useLiveStore.setState({ digitalTwinStatus: "open" }));
    await advance(1);
    expect(getDetail).toHaveBeenCalledTimes(41);
    expect(result.current.data?.status).toBe("execution_failed");
    await act(async () => { await result.current.refetch(); });
    expect(getDetail).toHaveBeenCalledTimes(42);
  });

  it.each([401, 403])("stops automatic reads after HTTP %s denial", async (status) => {
    getDetail.mockRejectedValue(new ApiClientError("Denied", "DENIED", status));
    renderHook(() => useIntentDetail("token", "intent", "workspace"), { wrapper });
    await advance(60_000);
    expect(getDetail).toHaveBeenCalledTimes(1);
  });

  it("restarts the exhausted detail budget after execute acceptance", async () => {
    getDetail.mockResolvedValue(response("validated"));
    vi.mocked(executeIntent).mockResolvedValue(response("execution_started") as unknown as Awaited<ReturnType<typeof executeIntent>>);
    const { result } = renderHook(() => ({ detail: { ...useIntentDetail("token", "intent", "workspace") }, execute: useExecuteIntent("token") }), { wrapper });
    await advance(1);
    for (let index = 0; index < 45; index += 1) await advance(15_100);
    expect(getDetail).toHaveBeenCalledTimes(40);
    getDetail.mockResolvedValue(response("execution_started"));
    await act(async () => { await result.current.execute.mutateAsync({ request: { intent_id: "intent", workspace_id: "workspace", manual_approval: true, cancel: false } }); });
    await advance(1);
    expect(getDetail).toHaveBeenCalledTimes(41);
    await advance(2_010);
    expect(getDetail).toHaveBeenCalledTimes(42);
  });

  it("does not poll without tenant and session context and cancels polling on unmount", async () => {
    const { rerender, unmount } = renderHook(({ token }) => useIntentDetail(token, "intent", "workspace"), { wrapper, initialProps: { token: null as string | null } });
    await advance(30_000);
    expect(getDetail).not.toHaveBeenCalled();
    rerender({ token: "token" });
    await advance(1);
    expect(getDetail).toHaveBeenCalledTimes(1);
    unmount();
    await advance(60_000);
    expect(getDetail).toHaveBeenCalledTimes(1);
  });
});

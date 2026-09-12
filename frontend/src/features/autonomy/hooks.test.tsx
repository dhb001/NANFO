import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutonomy } from "./hooks";
import { getAutonomy, stopAutonomy, updateAutonomy } from "./api";
import { autonomyFixture } from "./fixtures";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { ApiClientError } from "@/shared/lib/errors";

vi.mock("./api", () => ({ getAutonomy: vi.fn(), stopAutonomy: vi.fn(), updateAutonomy: vi.fn() }));

describe("scoped autonomy polling", () => {
  let client: QueryClient;
  const data = autonomyFixture();
  const read = vi.mocked(getAutonomy);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  async function advance(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    useAuthStore.setState({ accessToken: "token", generation: 1, endingSession: false,
      profile: { ...operatorProfile, permissions: ["read:telemetry", "write:config", "execute:rollback"] } });
    useWorkspaceStore.setState({ organizationId: "org", networkId: data.network_id, workspaceId: data.workspace_id });
    read.mockResolvedValue(data);
  });
  afterEach(() => { cleanup(); client.clear(); vi.useRealTimers(); });

  it("polls only mounted scope and aborts outstanding reads on context switch and unmount", async () => {
    const { unmount } = renderHook(() => useAutonomy(), { wrapper });
    await advance(1);
    await advance(10_010);
    expect(read).toHaveBeenCalledTimes(2);
    read.mockImplementation(() => new Promise(() => {}));
    await advance(10_010);
    const oldSignal = read.mock.calls.at(-1)?.[3];
    act(() => useWorkspaceStore.setState({ networkId: "network-b" }));
    await advance(1);
    expect(oldSignal?.aborted).toBe(true);
    expect(read.mock.calls.at(-1)?.[1]).toBe("network-b");
    const newSignal = read.mock.calls.at(-1)?.[3];
    unmount();
    expect(newSignal?.aborted).toBe(true);
    const reads = read.mock.calls.length;
    await advance(60_000);
    expect(read).toHaveBeenCalledTimes(reads);
  });

  it.each([401, 403])("stops automatic polling on HTTP %s and allows explicit retry", async (status) => {
    read.mockRejectedValue(new ApiClientError("Denied", "DENIED", status));
    const { result } = renderHook(() => useAutonomy(), { wrapper });
    await advance(60_000);
    expect(read).toHaveBeenCalledTimes(1);
    read.mockResolvedValue(data);
    await act(async () => { await result.current.status.refetch(); });
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("rejects old mutation callbacks after context or permission changes", async () => {
    const { result } = renderHook(() => useAutonomy(), { wrapper });
    await advance(1);
    const oldUpdate = result.current.update;
    act(() => useWorkspaceStore.setState({ networkId: "network-b" }));
    await act(async () => { await expect(oldUpdate.mutateAsync({ network_id: data.network_id, expected_revision: data.revision, mode: "monitor", checkpoint_sha256: null, approval_expires_at: null })).rejects.toThrow(); });
    expect(updateAutonomy).not.toHaveBeenCalled();
    const oldStop = result.current.stop;
    act(() => useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:telemetry"] } }));
    await act(async () => { await expect(oldStop.mutateAsync()).rejects.toThrow(); });
    expect(stopAutonomy).not.toHaveBeenCalled();
  });
});

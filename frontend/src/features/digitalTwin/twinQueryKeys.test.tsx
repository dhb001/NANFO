import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { listDevices } from "@/features/networks/api";
import { getSpatialHistory, getSpatialScene } from "./spatialApi";
import { useSpatialScene } from "./spatialHooks";
import { SpatialHistoryPanel } from "./SpatialHistoryPanel";
import { TwinInventoryPicker } from "./TwinInventoryPicker";

vi.mock("./spatialApi", () => ({ getSpatialScene: vi.fn(), putSpatialScene: vi.fn(), getSpatialHistory: vi.fn(), getSpatialRevision: vi.fn() }));
vi.mock("@/features/networks/api", () => ({ listDevices: vi.fn() }));

const scene = { version: 1 as const, revision: 2, coordinate_system: { units: "m" as const, up_axis: "y" as const }, objects: [] };

describe("Twin query keys carry session identity, never the credential", () => {
  let client: QueryClient;
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    useAuthStore.setState({ accessToken: "secret-token-1", userId: "user", generation: 1, endingSession: false, profile: operatorProfile });
    useWorkspaceStore.setState({ organizationId: "org", workspaceId: "ws", networkId: "network" });
    vi.mocked(getSpatialScene).mockResolvedValue(scene);
    vi.mocked(getSpatialHistory).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    vi.mocked(listDevices).mockResolvedValue({ success: true, data: { items: [], total: 0, page: 1, page_size: 20 }, errors: null, meta: { request_id: "r", timestamp: "t" } });
  });

  it("keeps caches and mounted reads across token rotation and uses the rotated credential next time", async () => {
    const { result } = renderHook(() => useSpatialScene(useAuthStore((state) => state.accessToken), "network", true), { wrapper });
    render(<>
      <SpatialHistoryPanel token="secret-token-1" networkId="network" current={scene} disabled onStage={vi.fn()} />
      <TwinInventoryPicker token="secret-token-1" networkId="network" selected={[]} onToggle={vi.fn()} />
    </>, { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(scene));
    await screen.findByText(/Inventory page 1/);
    await waitFor(() => expect(getSpatialHistory).toHaveBeenCalledTimes(1));
    const keys = client.getQueryCache().getAll().map((query) => JSON.stringify(query.queryKey));
    expect(keys).toHaveLength(3);
    for (const key of keys) expect(key).not.toContain("secret-token");
    act(() => useAuthStore.setState({ accessToken: "secret-token-2" }));
    expect(getSpatialScene).toHaveBeenCalledTimes(1);
    expect(listDevices).toHaveBeenCalledTimes(1);
    await act(async () => { await result.current.refetch(); });
    expect(vi.mocked(getSpatialScene).mock.calls.at(-1)?.[0]).toBe("secret-token-2");
    expect(client.getQueryCache().getAll()).toHaveLength(3);
  });

  it("separates caches by tenant scope", async () => {
    const { result, rerender } = renderHook(({ network }) => useSpatialScene("t", network, true), { wrapper, initialProps: { network: "network" } });
    await waitFor(() => expect(result.current.data).toEqual(scene));
    act(() => useWorkspaceStore.setState({ networkId: "other" }));
    rerender({ network: "other" });
    await waitFor(() => expect(getSpatialScene).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getSpatialScene).mock.calls[1][1]).toBe("other");
  });
});

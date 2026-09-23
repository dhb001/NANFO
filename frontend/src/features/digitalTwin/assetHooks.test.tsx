import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useCampusModelAssets, useUpsertCampusModelAssets } from "@/features/networks/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";

const api = vi.hoisted(() => ({ list: vi.fn(), save: vi.fn() }));
vi.mock("@/features/networks/api", () => ({ listCampusModelAssets: api.list, upsertCampusModelAssets: api.save }));
const pageData = (page: number) => ({ items: [{ campus_model_asset_id: `asset-${page}` }], total: 21, page, page_size: 20 });
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ accessToken: "token", userId: "user", generation: 1, endingSession: false });
  useWorkspaceStore.setState({ networkId: "network", workspaceId: "workspace", organizationId: "org" });
  api.list.mockImplementation(async (_token, _network, page) => ({ data: pageData(page) }));
});
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

it("isolates pages, retains cache over credential rotation and uses the latest credential for explicit reads", async () => {
  const { client, wrapper } = setup();
  const { result, rerender, unmount } = renderHook(({ page }) => useCampusModelAssets(useAuthStore((state) => state.accessToken), "network", page), { initialProps: { page: 1 }, wrapper });
  await waitFor(() => expect(result.current.data).toEqual(pageData(1)));
  rerender({ page: 2 });
  await waitFor(() => expect(result.current.data).toEqual(pageData(2)));
  act(() => useAuthStore.setState({ accessToken: "rotated" }));
  expect(api.list).toHaveBeenCalledTimes(2);
  await expect(result.current.readPage(1)).resolves.toEqual(pageData(1));
  expect(api.list).toHaveBeenLastCalledWith("rotated", "network", 1, 20, undefined);
  expect(result.current.data).toEqual(pageData(2));
  unmount(); client.clear();
});

it("discards stale page reads on tenant change and cancels the obsolete query", async () => {
  const { client, wrapper } = setup();
  let resolve!: (value: unknown) => void;
  api.list.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const { result, unmount } = renderHook(() => useCampusModelAssets("token", useWorkspaceStore((state) => state.networkId)), { wrapper });
  const signal = api.list.mock.calls[0][4] as AbortSignal;
  const oldRead = result.current.readPage;
  act(() => useWorkspaceStore.setState({ networkId: "other" }));
  await act(async () => resolve({ data: { ...pageData(1), items: [{ campus_model_asset_id: "stale" }] } }));
  await waitFor(() => expect(result.current.data).toEqual(pageData(1)));
  expect(signal.aborted).toBe(true);
  await expect(oldRead(1)).rejects.toThrow("Session context changed");
  expect(api.list).toHaveBeenCalledTimes(2);
  unmount(); client.clear();
});

it("invalidates all asset metadata pages after save", async () => {
  const { client, wrapper } = setup();
  api.save.mockResolvedValue({ data: { items: [], total: 1 } });
  const { result, unmount } = renderHook(() => ({
    first: useCampusModelAssets("token", "network", 1),
    second: useCampusModelAssets("token", "network", 2),
    save: useUpsertCampusModelAssets("token", "network"),
  }), { wrapper });
  await waitFor(() => expect(result.current.second.isSuccess).toBe(true));
  await act(async () => { await result.current.save.mutateAsync({ model_file_name: "a.glb", model_mime_type: "model/gltf-binary", model_data_base64: "AA==", model_sha256: "a".repeat(64), model_size_bytes: 1, mapping_by_device_id: {} }); });
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(4));
  unmount(); client.clear();
});

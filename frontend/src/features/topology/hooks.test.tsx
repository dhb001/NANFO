import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useTopologyGraph } from "./hooks";
import { useLiveStore } from "@/features/realtime/store";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";

const getGraph = vi.fn();
vi.mock("./api", () => ({ getTopologyGraphAll: (...args: unknown[]) => getGraph(...args) }));
beforeEach(() => {
  getGraph.mockReset();
  useAuthStore.getState().setSession({ accessToken: "token", refreshToken: "refresh", userId: operatorProfile.user_id, profile: operatorProfile });
  useLiveStore.getState().reset();
});

it("does not retire a tombstone for a partial or pre-removal request, only a confirmed later snapshot", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  let resolve!: (value: unknown) => void;
  getGraph.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const { result } = renderHook(() => useTopologyGraph("token", "network"), { wrapper });
  act(() => useLiveStore.getState().applyTopologyDelta({ delta_type: "remove", node: { device_id: "d" } }));
  await act(async () => resolve({ data: { nodes: [], edges: [] }, nextCursor: null }));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(useLiveStore.getState().topologyTombstones.d).toBeDefined();
  getGraph.mockResolvedValueOnce({ data: { nodes: [], edges: [] }, nextCursor: "more" });
  await act(async () => { await result.current.refetch(); });
  expect(useLiveStore.getState().topologyTombstones.d).toBeDefined();
  getGraph.mockResolvedValueOnce({ data: { nodes: [], edges: [] }, nextCursor: null });
  await act(async () => { await result.current.refetch(); });
  await waitFor(() => expect(useLiveStore.getState().topologyTombstones.d).toBeUndefined());
});

it("keeps a delta that arrived during the crawl applied to the fetched graph", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  let resolve!: (value: unknown) => void;
  getGraph.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const { result } = renderHook(() => useTopologyGraph("token", "network"), { wrapper });
  act(() => useLiveStore.getState().applyTopologyDelta({ delta_type: "update", node: { device_id: "a", status: "down" } }, "2026-09-20T00:00:00Z"));
  await act(async () => resolve({ data: { nodes: [{ device_id: "a", hostname: "a", device_type: "router", status: "up", spatial_ref_id: null }], edges: [] }, nextCursor: null }));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  // The crawl started before the delta; the cached result must not regress it.
  expect(result.current.data?.data.nodes[0].status).toBe("down");
  expect(getGraph.mock.calls[0][2]).toMatchObject({ signal: expect.any(AbortSignal) });
});

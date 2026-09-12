import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useTopologyGraph } from "./hooks";
import { useLiveStore } from "@/features/realtime/store";

const getGraph = vi.fn();
vi.mock("./api", () => ({ getTopologyGraphAll: (...args: unknown[]) => getGraph(...args) }));
beforeEach(() => { getGraph.mockReset(); useLiveStore.getState().reset(); });

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

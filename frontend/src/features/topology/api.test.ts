import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getTopologyGraph,
  getTopologyGraphAll,
} from "@/features/topology/api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function okEnvelope<T>(data: T, nextCursor: string | null = null) {
  return {
    success: true,
    data,
    meta: {
      request_id: "req-topology",
      timestamp: "2026-09-02T00:00:00Z",
      next_cursor: nextCursor,
    },
    errors: null,
  };
}

describe("topology api", () => {
  it("requests paginated graph page with limit and optional cursor", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () =>
        okEnvelope(
          {
            nodes: [],
            edges: [],
          },
          "cursor-2",
        ),
    });

    const response = await getTopologyGraph("token-1", "network-1", 150, "cursor-1");

    expect(response.nextCursor).toBe("cursor-2");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/topology/graph?");
    expect(requestUrl).toContain("network_id=network-1");
    expect(requestUrl).toContain("limit=150");
    expect(requestUrl).toContain("cursor=cursor-1");
    expect(requestInit.headers).toMatchObject({ Authorization: "Bearer token-1" });
  });

  it("aggregates paginated graph pages with deterministic deduplication", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () =>
          okEnvelope(
            {
              nodes: [
                {
                  device_id: "device-2",
                  hostname: "edge-2",
                  device_type: "switch",
                  status: "active",
                  spatial_ref_id: "campus-a/bld-2/f01/zone/device-2",
                },
                {
                  device_id: "device-1",
                  hostname: "edge-1",
                  device_type: "switch",
                  status: "active",
                  spatial_ref_id: "campus-a/bld-1/f01/zone/device-1",
                },
              ],
              edges: [
                {
                  source_id: "device-1",
                  target_id: "device-2",
                  edge_type: "connected_to",
                  metadata: { one: 1 },
                },
              ],
            },
            "cursor-2",
          ),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () =>
          okEnvelope(
            {
              nodes: [
                {
                  device_id: "device-1",
                  hostname: "edge-1-updated",
                  device_type: "switch",
                  status: "offline",
                  spatial_ref_id: "campus-a/bld-1/f02/zone/device-1",
                },
                {
                  device_id: "device-3",
                  hostname: "core-3",
                  device_type: "router",
                  status: "active",
                  spatial_ref_id: "campus-a/bld-3/f01/zone/device-3",
                },
              ],
              edges: [
                {
                  source_id: "device-1",
                  target_id: "device-2",
                  edge_type: "connected_to",
                  metadata: { two: 2 },
                },
                {
                  source_id: "device-2",
                  target_id: "device-3",
                  edge_type: "depends_on",
                  metadata: {},
                },
              ],
            },
            null,
          ),
      });

    const response = await getTopologyGraphAll("token-1", "network-1", {
      pageLimit: 2,
      maxPages: 10,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(response.nextCursor).toBeNull();
    expect(response.data.nodes.map((node) => node.device_id)).toEqual([
      "device-1",
      "device-2",
      "device-3",
    ]);
    expect(response.data.nodes[0].hostname).toBe("edge-1-updated");
    expect(response.data.nodes[0].status).toBe("offline");

    expect(response.data.edges).toHaveLength(2);
    const mergedEdge = response.data.edges.find((edge) => edge.source_id === "device-1" && edge.target_id === "device-2");
    expect(mergedEdge?.metadata).toEqual({ one: 1, two: 2 });
  });

  it("stops pagination at maxPages and returns trailing cursor", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () =>
          okEnvelope(
            {
              nodes: [
                {
                  device_id: "device-1",
                  hostname: "node-1",
                  device_type: "switch",
                  status: "active",
                  spatial_ref_id: null,
                },
              ],
              edges: [],
            },
            "cursor-2",
          ),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () =>
          okEnvelope(
            {
              nodes: [
                {
                  device_id: "device-2",
                  hostname: "node-2",
                  device_type: "switch",
                  status: "active",
                  spatial_ref_id: null,
                },
              ],
              edges: [],
            },
            "cursor-3",
          ),
      });

    const response = await getTopologyGraphAll("token-1", "network-1", {
      pageLimit: 1,
      maxPages: 2,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(response.data.nodes).toHaveLength(2);
    expect(response.nextCursor).toBe("cursor-3");
  });
});

import { describe, expect, it } from "vitest";
import { sanitizeRangeInput, summarizeImpactStats, summarizeNeighbourStats } from "@/features/topology/logic";

describe("topology analysis logic", () => {
  it("summarizes neighbour stats by hop depth", () => {
    const summary = summarizeNeighbourStats({
      device: {
        device_id: "device-1",
        hostname: "core-1",
        device_type: "router",
        status: "active",
        spatial_ref_id: null,
      },
      neighbours: [
        {
          device_id: "device-2",
          hostname: "edge-2",
          device_type: "switch",
          status: "active",
          spatial_ref_id: null,
          edge_type: "connected_to",
          edge_metadata: {},
          direction: "outbound",
          hop_depth: 1,
        },
        {
          device_id: "device-3",
          hostname: "edge-3",
          device_type: "switch",
          status: "active",
          spatial_ref_id: null,
          edge_type: "connected_to",
          edge_metadata: {},
          direction: "inbound",
          hop_depth: 2,
        },
        {
          device_id: "device-4",
          hostname: "edge-4",
          device_type: "switch",
          status: "active",
          spatial_ref_id: null,
          edge_type: "connected_to",
          edge_metadata: {},
          direction: "inbound",
          hop_depth: 2,
        },
      ],
      depth: 2,
      total: 3,
    });

    expect(summary.total).toBe(3);
    expect(summary.byHopDepth).toEqual({ 1: 1, 2: 2 });
  });

  it("summarizes impact stats by hop depth", () => {
    const summary = summarizeImpactStats({
      device: {
        device_id: "device-1",
        hostname: "core-1",
        device_type: "router",
        status: "active",
        spatial_ref_id: null,
      },
      impacts: [
        {
          device_id: "device-2",
          hostname: "edge-2",
          device_type: "switch",
          status: "active",
          spatial_ref_id: null,
          hop_depth: 1,
        },
        {
          device_id: "device-3",
          hostname: "edge-3",
          device_type: "switch",
          status: "active",
          spatial_ref_id: null,
          hop_depth: 3,
        },
      ],
      max_hops: 3,
      total: 2,
    });

    expect(summary.total).toBe(2);
    expect(summary.byHopDepth).toEqual({ 1: 1, 3: 1 });
  });

  it("sanitizes range inputs", () => {
    expect(sanitizeRangeInput(4.8, 1, 6)).toBe(4);
    expect(sanitizeRangeInput(100, 1, 6)).toBe(6);
    expect(sanitizeRangeInput(-5, 1, 6)).toBe(1);
    expect(sanitizeRangeInput(Number.NaN, 1, 6)).toBe(1);
  });
});

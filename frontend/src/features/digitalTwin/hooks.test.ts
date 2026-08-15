import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { useTwinLinks, useTwinNodes } from "@/features/digitalTwin/hooks";
import { useLiveStore } from "@/features/realtime/store";

describe("digital twin hooks", () => {
  it("merges base topology and live deltas into node list", () => {
    useLiveStore.setState({
      topologyByDeviceId: {
        "device-2": {
          device_id: "device-2",
          hostname: "access-2-live",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/rack-2",
        },
      },
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
      alerts: [],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "closed",
      digitalTwinStatus: "closed",
    });

    const { result } = renderHook(() =>
      useTwinNodes([
        {
          device_id: "device-1",
          hostname: "core-1",
          device_type: "router",
          status: "active",
          spatial_ref_id: null,
        },
      ]),
    );

    expect(result.current).toHaveLength(2);
    expect(result.current.find((node) => node.id === "device-1")?.hostname).toBe("core-1");
    expect(result.current.find((node) => node.id === "device-2")?.hostname).toBe("access-2-live");
  });

  it("builds links only when source and target nodes exist", () => {
    const nodes = [
      { id: "a", hostname: "A", type: "router", status: "active", x: 0, y: 0, z: 0, spatialRefId: null },
      { id: "b", hostname: "B", type: "switch", status: "active", x: 1, y: 0, z: 1, spatialRefId: null },
    ];

    const { result } = renderHook(() =>
      useTwinLinks(nodes, [
        { source_id: "a", target_id: "b", edge_type: "connected_to", metadata: {} },
        { source_id: "a", target_id: "missing", edge_type: "connected_to", metadata: {} },
      ]),
    );

    expect(result.current).toHaveLength(1);
    expect(result.current[0].edgeType).toBe("connected_to");
  });
});

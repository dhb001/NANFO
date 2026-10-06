import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useLiveStore } from "@/features/realtime/store";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { TWIN_ALERT_LIMIT, useTwinSceneData } from "./useTwinSceneData";

const mocks = vi.hoisted(() => ({ graph: vi.fn(), alerts: vi.fn(), spatial: vi.fn() }));

vi.mock("@/features/topology/hooks", () => ({ useTopologyGraph: (...args: unknown[]) => mocks.graph(...args) }));
vi.mock("@/features/reliability/hooks", () => ({ useAlertsQuery: (...args: unknown[]) => mocks.alerts(...args) }));
vi.mock("./spatialHooks", () => ({ useSpatialScene: (...args: unknown[]) => mocks.spatial(...args) }));

const NETWORK = "00000000-0000-0000-0000-000000000333";
const nodes = [
  { device_id: "d1", hostname: "edge-1", device_type: "switch", status: "active", spatial_ref_id: " campus-a/building-1/f01/sw " },
  { device_id: "d2", hostname: "edge-2", device_type: "switch", status: "active", spatial_ref_id: null },
];
const telemetry = (value: number) => ({
  "d1:latency_ms": { event_id: `e-${value}`, device_id: "d1", network_id: NETWORK, workspace_id: "w", metric: "latency_ms", value, unit: "ms", observed_at: new Date().toISOString(), source: "runtime", tags: {} },
});

describe("useTwinSceneData", () => {
  beforeEach(() => {
    mocks.graph.mockReset().mockReturnValue({ isLoading: false, isError: false, isFetching: false, data: { data: { nodes, edges: [] }, nextCursor: null }, refetch: vi.fn() });
    mocks.alerts.mockReset().mockReturnValue({ isLoading: false, isError: false, data: { items: [
      { alert_id: "a1", alert_key: "k1", status: "active", severity: "warning", updated_at: "2026-09-24T00:00:00Z", payload: { device_id: "d2", metric: "latency_ms" } },
    ] }, refetch: vi.fn() });
    mocks.spatial.mockReset().mockReturnValue({ data: undefined, isError: false, isFetching: false });
    useAuthStore.setState({ profile: operatorProfile, accessToken: "token-1" });
    useWorkspaceStore.setState({ networkId: NETWORK, workspaceId: "w" });
    useLiveStore.setState({ topologyByDeviceId: {}, topologyTombstones: {}, telemetryByDeviceMetric: {}, telemetryKeysNewestFirst: [], alerts: [], sceneObjects: {}, sceneObjectIdsNewestFirst: [] });
  });

  it("keeps topology geometry identical when telemetry changes and never embeds telemetry in nodes", async () => {
    const { result } = renderHook(() => useTwinSceneData());
    const scene = result.current.scene;
    expect(scene.nodes.map((node) => [node.id, node.persistedSpatialRefId])).toEqual([["d1", "campus-a/building-1/f01/sw"], ["d2", null]]);
    await act(async () => {
      useLiveStore.setState({ telemetryByDeviceMetric: telemetry(130), telemetryKeysNewestFirst: ["d1:latency_ms"] });
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    });
    expect(result.current.scene).toBe(scene);
    expect(result.current.congestionByDevice.d1?.severity).toBe("high");
    expect(result.current.viewportStatus).toEqual({ kind: "ready" });
  });

  it("uses active backend alerts (REST + live) as the authoritative severity for known devices", () => {
    useLiveStore.setState({ alerts: [
      { event_id: "l1", event_type: "alert.generated", source: "telemetry", timestamp: "2026-09-24T01:00:00Z", payload: { alert_id: "a9", device_id: "d1" } },
      { event_id: "l2", event_type: "alert.generated", source: "telemetry", timestamp: "2026-09-24T01:00:00Z", payload: { alert_id: "a8", device_id: "unknown-device" } },
    ] });
    const { result } = renderHook(() => useTwinSceneData());
    expect([...result.current.alertingDeviceIds].sort()).toEqual(["d1", "d2"]);
    expect(mocks.alerts).toHaveBeenLastCalledWith("token-1", { status: "active", networkId: NETWORK, workspaceId: "w", limit: TWIN_ALERT_LIMIT }, true);
    expect(result.current.alertsEnabled).toBe(true);
  });

  it("disables the alert snapshot without read:telemetry and reports the data state for the view", () => {
    useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:topology"] } });
    mocks.graph.mockReturnValue({ isLoading: true, isError: false, data: undefined, refetch: vi.fn() });
    const { result, rerender } = renderHook(() => useTwinSceneData());
    expect(mocks.alerts).toHaveBeenLastCalledWith("token-1", expect.anything(), false);
    expect(result.current.alertsEnabled).toBe(false);
    expect(result.current.viewportStatus).toMatchObject({ kind: "loading" });
    act(() => useWorkspaceStore.setState({ networkId: null }));
    rerender();
    expect(result.current.viewportStatus).toMatchObject({ kind: "no-network" });
    expect(result.current.graphComplete).toBe(false);
  });

  it("applies the session mapping as the effective reference but keeps the persisted one separate", () => {
    const mapping = { d2: "campus-b/building-9/f02/ap" };
    const { result } = renderHook(() => useTwinSceneData(mapping));
    expect(result.current.scene.nodeById.d2).toMatchObject({ spatialRefId: "campus-b/building-9/f02/ap", persistedSpatialRefId: null });
  });
});

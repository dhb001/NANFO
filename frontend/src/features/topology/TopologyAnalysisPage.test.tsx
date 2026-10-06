import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TopologyAnalysisPage } from "@/features/topology/TopologyAnalysisPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";

const mockUseTopologyGraph = vi.fn();
const mockUseTopologyNeighbours = vi.fn();
const mockUseTopologyImpact = vi.fn();
const mockUseReconcileTopology = vi.fn();

vi.mock("@/features/topology/hooks", () => ({
  useTopologyGraph: (...args: unknown[]) => mockUseTopologyGraph(...args),
  useTopologyNeighbours: (...args: unknown[]) => mockUseTopologyNeighbours(...args),
  useTopologyImpact: (...args: unknown[]) => mockUseTopologyImpact(...args),
  useReconcileTopology: (...args: unknown[]) => mockUseReconcileTopology(...args),
}));

function queryResult<T>(data: T, refetch = vi.fn()) {
  return {
    isLoading: false,
    isError: false,
    data,
    refetch,
  };
}

describe("TopologyAnalysisPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    useAuthStore.setState({
      profile: operatorProfile,
      accessToken: "token-1",
      refreshToken: "refresh-1",
      userId: "00000000-0000-0000-0000-000000000123",
    });
    useWorkspaceStore.setState({
      organizationId: "00000000-0000-0000-0000-000000000111",
      workspaceId: "00000000-0000-0000-0000-000000000222",
      networkId: "00000000-0000-0000-0000-000000000333",
    });
    useLiveStore.setState({
      topologyByDeviceId: {},
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

    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/edge-1",
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNeighbours.mockReturnValue(
      queryResult({
        device: {
          device_id: "00000000-0000-0000-0000-000000000444",
          hostname: "edge-1",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/edge-1",
        },
        neighbours: [
          {
            device_id: "00000000-0000-0000-0000-000000000445",
            hostname: "core-1",
            device_type: "router",
            status: "active",
            spatial_ref_id: "campus-a/core-1",
            edge_type: "connected_to",
            edge_metadata: { link_quality: "good" },
            direction: "inbound",
            hop_depth: 1,
          },
        ],
        depth: 2,
        total: 1,
      }),
    );
    mockUseTopologyImpact.mockReturnValue(
      queryResult({
        device: {
          device_id: "00000000-0000-0000-0000-000000000444",
          hostname: "edge-1",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/edge-1",
        },
        impacts: [
          {
            device_id: "00000000-0000-0000-0000-000000000446",
            hostname: "dist-1",
            device_type: "switch",
            status: "active",
            spatial_ref_id: null,
            hop_depth: 2,
          },
        ],
        max_hops: 3,
        total: 1,
      }),
    );
    mockUseReconcileTopology.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
      data: null,
    });
  });

  it("renders neighbour analysis details", () => {
    render(<TopologyAnalysisPage />);

    expect(screen.getByText("Topology Analysis")).toBeInTheDocument();
    expect(screen.getByText("Neighbour Analysis")).toBeInTheDocument();
    expect(screen.getByText("core-1")).toBeInTheDocument();
    expect(screen.getByText("hop 1: 1")).toBeInTheDocument();
  });

  it("switches to impact analysis tab", async () => {
    const user = userEvent.setup();
    render(<TopologyAnalysisPage />);

    await user.click(screen.getByRole("button", { name: "Impact" }));

    expect(screen.getByText("Impact Analysis")).toBeInTheDocument();
    expect(screen.getByText("dist-1")).toBeInTheDocument();
    expect(screen.getByText("hop 2: 1")).toBeInTheDocument();
  });

  it("runs reconcile action and renders reconcile result", async () => {
    const user = userEvent.setup();
    const mutate = vi.fn();
    mockUseReconcileTopology.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
      error: null,
      data: {
        reconcile_id: "rec-1",
        network_id: "00000000-0000-0000-0000-000000000333",
        status: "completed",
        checked_nodes: 4,
        checked_edges: 3,
        missing_workspace_nodes: 1,
        workspace_backfilled_nodes: 1,
        warning: null,
      },
    });

    render(<TopologyAnalysisPage />);
    await user.click(screen.getByRole("button", { name: "Run Reconcile" }));

    expect(mutate).toHaveBeenCalled();
    expect(screen.getByText("reconcile_id: rec-1")).toBeInTheDocument();
    expect(screen.queryByText(/Inventory repair/)).not.toBeInTheDocument();
  });

  it("shows the inventory-driven repair counts and watermark when the backend reports them (C13)", () => {
    mockUseReconcileTopology.mockReturnValue({
      mutate: vi.fn(), isPending: false, isError: false, error: null,
      data: {
        reconcile_id: "rec-2", network_id: "00000000-0000-0000-0000-000000000333", status: "completed", checked_nodes: 4, checked_edges: 3,
        missing_workspace_nodes: 0, workspace_backfilled_nodes: 0, active_devices: 5, upserted_nodes: 2, tombstoned_nodes: 1,
        skipped_newer_nodes: 3, watermark_sequence: 42,
      },
    });
    render(<TopologyAnalysisPage />);
    expect(screen.getByText(/Inventory repair: 5 active devices; 2 nodes upserted;\s+1 tombstoned; 3 skipped \(newer graph state kept\)\. Inventory sequence reached: 42\./)).toBeInTheDocument();
    expect(screen.getByText("reconcile completed")).toHaveClass("badge--ok");
  });

  it("refetches topology analyses when live topology delta fingerprint changes", async () => {
    const neighboursRefetch = vi.fn();
    const impactRefetch = vi.fn();
    mockUseTopologyNeighbours.mockReturnValue(
      queryResult(
        {
          device: {
            device_id: "00000000-0000-0000-0000-000000000444",
            hostname: "edge-1",
            device_type: "switch",
            status: "active",
            spatial_ref_id: null,
          },
          neighbours: [
            {
              device_id: "00000000-0000-0000-0000-000000000445",
              hostname: "core-1",
              device_type: "router",
              status: "active",
              spatial_ref_id: null,
              edge_type: "connected_to",
              edge_metadata: {},
              direction: "outbound",
              hop_depth: 1,
            },
          ],
          depth: 2,
          total: 1,
        },
        neighboursRefetch,
      ),
    );
    mockUseTopologyImpact.mockReturnValue(
      queryResult(
        {
          device: {
            device_id: "00000000-0000-0000-0000-000000000444",
            hostname: "edge-1",
            device_type: "switch",
            status: "active",
            spatial_ref_id: null,
          },
          impacts: [
            {
              device_id: "00000000-0000-0000-0000-000000000446",
              hostname: "dist-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: null,
              hop_depth: 1,
            },
          ],
          max_hops: 3,
          total: 1,
        },
        impactRefetch,
      ),
    );

    render(<TopologyAnalysisPage />);

    await act(async () => {
      useLiveStore.setState({
        topologyByDeviceId: {
          "00000000-0000-0000-0000-000000000445": {
            device_id: "00000000-0000-0000-0000-000000000445",
            hostname: "core-1",
            device_type: "router",
            status: "active",
            spatial_ref_id: null,
          },
        },
      });
    });

    await waitFor(() => {
      expect(neighboursRefetch).toHaveBeenCalled();
      expect(impactRefetch).toHaveBeenCalled();
    });
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TwinPage } from "@/features/digitalTwin/TwinPage";
import { parseImportSummary } from "@/features/digitalTwin/twinImport";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";

const mockUseTopologyGraph = vi.fn();
const mockUseTopologyNode = vi.fn();
const mockUpdateDeviceSpatialRefMutateAsync = vi.fn();
const mockUpsertCampusBuildingsMutateAsync = vi.fn();
const mockUpsertCampusModelAssetsMutateAsync = vi.fn();
const mockUpsertDeviceGroupsMutateAsync = vi.fn();
const mockUseCampusBuildings = vi.fn();
const mockUseCampusModelAssets = vi.fn();
const mockUseDeviceGroups = vi.fn();
const mockUseUpsertCampusBuildings = vi.fn();
const mockUseUpsertCampusModelAssets = vi.fn();
const mockUseUpsertDeviceGroups = vi.fn();

const navigateMock = vi.fn();

const cryptoSubtleDigestMock = vi.fn();
const spatialMocks = vi.hoisted(() => ({ data: undefined as import("@/shared/types/spatial").SpatialSceneSnapshot | undefined }));

vi.mock("./spatialHooks", () => ({
  useSpatialScene: () => ({ data: spatialMocks.data, isFetching: false, isError: false, refetch: vi.fn() }),
  useSaveSpatialScene: () => ({ isPending: false, mutateAsync: vi.fn() }),
}));

Object.defineProperty(globalThis, "crypto", {
  configurable: true,
  value: {
    subtle: {
      digest: (...args: unknown[]) => cryptoSubtleDigestMock(...args),
    },
  },
});

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/features/topology/hooks", () => ({
  useTopologyGraph: (...args: unknown[]) => mockUseTopologyGraph(...args),
  useTopologyNode: (...args: unknown[]) => mockUseTopologyNode(...args),
}));

vi.mock("@/features/networks/hooks", () => ({
  useUpdateDeviceSpatialRef: () => ({
    mutateAsync: mockUpdateDeviceSpatialRefMutateAsync,
    isPending: false,
  }),
  useCampusBuildings: (...args: unknown[]) => mockUseCampusBuildings(...args),
  useCampusModelAssets: (...args: unknown[]) => mockUseCampusModelAssets(...args),
  useDeviceGroups: (...args: unknown[]) => mockUseDeviceGroups(...args),
  useUpsertCampusBuildings: (...args: unknown[]) => mockUseUpsertCampusBuildings(...args),
  useUpsertCampusModelAssets: (...args: unknown[]) => mockUseUpsertCampusModelAssets(...args),
  useUpsertDeviceGroups: (...args: unknown[]) => mockUseUpsertDeviceGroups(...args),
}));

const twinScenePropsSpy = vi.fn();

vi.mock("@/features/digitalTwin/TwinScene", () => ({
  TwinScene: (props: {
    layers: Record<string, boolean>;
    nodes: unknown[];
    links: unknown[];
    overlays: unknown[];
    alerts?: Array<{ event_type: string; payload: Record<string, unknown> }>;
    buildingViewState?: {
      selectedBuildingId?: string | null;
      selectedFloorKey?: string | null;
      floorFilterEnabled?: boolean;
      visibleBuildingIds?: ReadonlySet<string>;
    };
    onSelectBuilding?: (buildingId: string) => void;
  }) => {
    twinScenePropsSpy(props);
    return (
    <div data-testid="twin-scene">
      scene nodes={props.nodes.length} links={props.links.length} overlays={props.overlays.length} congestion={String(props.layers.showCongestion)}
    </div>
    );
  },
}));

vi.mock("@/features/digitalTwin/twinImport", async () => {
  const actual = await vi.importActual<typeof import("@/features/digitalTwin/twinImport")>("@/features/digitalTwin/twinImport");
  return actual;
});

function queryResult<T>(data: T | null, options?: { isLoading?: boolean; isError?: boolean; refetch?: () => void }) {
  return {
    isLoading: options?.isLoading ?? false,
    isError: options?.isError ?? false,
    data,
    refetch: options?.refetch ?? vi.fn().mockResolvedValue({ data, isError: false }),
  };
}

async function waitForTwinScene() {
  return screen.findByTestId("twin-scene", {}, { timeout: 5000 });
}

describe("TwinPage", () => {
  beforeEach(() => {
    spatialMocks.data = undefined;
    vi.clearAllMocks();
    navigateMock.mockReset();
    twinScenePropsSpy.mockReset();
    mockUseCampusBuildings.mockReset();
    mockUseCampusModelAssets.mockReset();
    mockUseDeviceGroups.mockReset();
    mockUseUpsertCampusBuildings.mockReset();
    mockUseUpsertCampusModelAssets.mockReset();
    mockUseUpsertDeviceGroups.mockReset();
    mockUpsertCampusBuildingsMutateAsync.mockReset();
    mockUpsertCampusModelAssetsMutateAsync.mockReset();
    mockUpsertDeviceGroupsMutateAsync.mockReset();

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
      telemetryByDeviceMetric: {
        "00000000-0000-0000-0000-000000000444:cpu_usage": {
          event_id: "evt-1",
          device_id: "00000000-0000-0000-0000-000000000444",
          network_id: "00000000-0000-0000-0000-000000000333",
          workspace_id: "00000000-0000-0000-0000-000000000222",
          metric: "cpu_usage",
          value: 45,
          unit: "%",
          observed_at: new Date().toISOString(),
          source: "runtime",
          tags: {},
        },
      },
      telemetryKeysNewestFirst: ["00000000-0000-0000-0000-000000000444:cpu_usage"],
      sceneObjects: {
        "simulation-state": {
          id: "simulation-state",
          object_type: "simulation_state",
          status: "queued",
        },
      },
      sceneObjectIdsNewestFirst: ["simulation-state"],
      alerts: [],
      topologyStatus: "open",
      telemetryStatus: "open",
      alertsStatus: "closed",
      digitalTwinStatus: "open",
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });
    mockUpdateDeviceSpatialRefMutateAsync.mockResolvedValue({});
    mockUpsertCampusBuildingsMutateAsync.mockResolvedValue({
      items: [],
      total: 0,
    });
    mockUpsertCampusModelAssetsMutateAsync.mockResolvedValue({
      items: [],
      total: 0,
    });
    mockUpsertDeviceGroupsMutateAsync.mockResolvedValue({
      items: [],
      total: 0,
    });
    mockUseCampusBuildings.mockReturnValue(
      queryResult({
        items: [],
        total: 0,
      }),
    );
    mockUseCampusModelAssets.mockReturnValue(
      queryResult({
        items: [],
        total: 0,
      }),
    );
    mockUseDeviceGroups.mockReturnValue(
      queryResult({
        items: [],
        total: 0,
      }),
    );
    mockUseUpsertCampusBuildings.mockReturnValue({
      mutateAsync: mockUpsertCampusBuildingsMutateAsync,
      isPending: false,
    });
    mockUseUpsertCampusModelAssets.mockReturnValue({
      mutateAsync: mockUpsertCampusModelAssetsMutateAsync,
      isPending: false,
    });
    mockUseUpsertDeviceGroups.mockReturnValue({
      mutateAsync: mockUpsertDeviceGroupsMutateAsync,
      isPending: false,
    });
  });

  it("renders loading state", async () => {
    mockUseTopologyGraph.mockReturnValue(queryResult(null, { isLoading: true }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);

    expect(await screen.findByText(/loading/i)).toBeInTheDocument();
  });

  it("restores explicitly, confirms replacement, and revokes URLs on scope change and unmount", async () => {
    const user = userEvent.setup();
    const id = "00000000-0000-0000-0000-000000000444";
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: id, hostname: "edge", device_type: "switch", status: "active", spatial_ref_id: null }], edges: [] }, nextCursor: null }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    const json = '{"asset":{"version":"2.0"},"scene":0,"scenes":[{}]}';
    const bytes = new TextEncoder().encode(json);
    const record = { campus_model_asset_id: "asset", network_id: useWorkspaceStore.getState().networkId, model_file_name: "saved.gltf", model_mime_type: "model/gltf+json",
      model_data_base64: btoa(json), model_size_bytes: bytes.length, model_sha256: "0".repeat(64), mapping_by_device_id: { [id]: "campus/building/f1" }, updated_at: "2026-09-10T00:00:00Z" };
    mockUseCampusModelAssets.mockReturnValue(queryResult({ items: [record, { ...record, campus_model_asset_id: "newer", model_file_name: "newer.gltf", mapping_by_device_id: {} }], total: 2 }));
    cryptoSubtleDigestMock.mockResolvedValue(new Uint8Array(32).buffer);
    const create = vi.fn().mockReturnValueOnce("blob:first").mockReturnValueOnce("blob:second").mockReturnValueOnce("blob:third");
    const revoke = vi.fn();
    const previousCreate = URL.createObjectURL;
    const previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = create; URL.revokeObjectURL = revoke;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { unmount } = render(<TwinPage />);
    await waitForTwinScene();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Restore Persisted Model" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Persisted model asset"), "asset");
    expect(create).not.toHaveBeenCalled();
    await user.selectOptions(screen.getByLabelText("Inspect node"), id);
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(twinScenePropsSpy.mock.calls.at(-1)?.[0].nodes[0].spatialRefId).toBe("campus/building/f1");
    expect(twinScenePropsSpy.mock.calls.at(-1)?.[0].modelRegistration).toBeNull();
    await user.type(screen.getByLabelText("Registration source"), "survey");
    await user.click(screen.getByRole("button", { name: "Apply local registration" }));
    expect(twinScenePropsSpy.mock.calls.at(-1)?.[0].modelRegistration.scale).toEqual([1, 1, 1]);
    spatialMocks.data = { version: 1, revision: 1, coordinate_system: { units: "m", up_axis: "y" }, objects: [{
      object_id: "placement", parent_id: null, object_type: "device", name: "edge", device_id: id,
      position: { x: 123, y: 4, z: 5 }, rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "survey", accuracy_m: 0.1 },
    }] };
    await user.click(screen.getByRole("button", { name: "Labels" }));
    expect(twinScenePropsSpy.mock.calls.at(-1)?.[0]).toMatchObject({ selectedNodeId: id, nodes: [expect.objectContaining({ x: 123, spatialRefId: "campus/building/f1" })] });
    confirm.mockReturnValue(false);
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(create).toHaveBeenCalledTimes(1);
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:first"));
    expect(twinScenePropsSpy.mock.calls.at(-1)?.[0].modelRegistration).toBeNull();
    act(() => useWorkspaceStore.getState().setNetworkId("other"));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:second"));
    await waitFor(() => expect(screen.getByText("model idle", { exact: true })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Persisted model asset"), "asset");
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    expect(await screen.findByText("Persisted model belongs to another network.")).toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(2);
    act(() => useWorkspaceStore.getState().setNetworkId(record.network_id));
    await user.selectOptions(await screen.findByLabelText("Persisted model asset"), "asset");
    await user.click(await screen.findByRole("button", { name: "Restore Persisted Model" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(3));
    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:third");
    URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke;
    confirm.mockRestore();
  }, 15_000);

  it("retains an off-page selection across paging and token rotation, then refreshes its source page before binary restore", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active" }], edges: [] }, nextCursor: null }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    const json = '{"asset":{"version":"2.0"},"scenes":[{}],"scene":0}';
    const record = { campus_model_asset_id: "older", network_id: useWorkspaceStore.getState().networkId, model_file_name: "older.gltf", model_mime_type: "model/gltf+json",
      storage_backend: "inline", model_size_bytes: new TextEncoder().encode(json).length, model_sha256: "0".repeat(64), mapping_by_device_id: {}, updated_at: "2026-09-10T00:00:00Z" };
    const first = { items: [record], total: 21, page: 1, page_size: 20 };
    const readPage = vi.fn().mockResolvedValue(first);
    mockUseCampusModelAssets.mockImplementation((_token, _network, page) => ({ ...queryResult(page === 1 ? first : { items: [{ ...record, campus_model_asset_id: "newer", model_file_name: "newer.gltf" }], total: 21, page: 2, page_size: 20 }), readPage }));
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(json, { headers: { "Content-Type": "application/octet-stream", ETag: `"sha256:${record.model_sha256}"` } }));
    cryptoSubtleDigestMock.mockResolvedValue(new Uint8Array(32).buffer);
    const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn().mockReturnValue("blob:paged"); URL.revokeObjectURL = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { unmount } = render(<TwinPage />);
    await waitForTwinScene();
    await user.selectOptions(screen.getByLabelText("Persisted model asset"), "older");
    await user.click(screen.getByRole("button", { name: "Next asset page" }));
    expect(screen.getByLabelText("Persisted model asset")).toHaveValue("older");
    expect(screen.getByRole("button", { name: "Next asset page" })).toBeDisabled();
    act(() => useAuthStore.setState({ accessToken: "rotated" }));
    expect(screen.getByLabelText("Persisted model asset")).toHaveValue("older");
    await user.click(screen.getByRole("button", { name: "Reload model assets" }));
    expect(screen.getByLabelText("Persisted model asset")).toHaveValue("older");
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(readPage).toHaveBeenCalledWith(1);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/campus-model-assets/older/download"), expect.objectContaining({ headers: { Authorization: "Bearer rotated" } }));
    readPage.mockResolvedValue({ ...first, items: [] });
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    expect(await screen.findByText("Persisted model is no longer available. Refresh and try again.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    act(() => useWorkspaceStore.getState().setNetworkId("other"));
    expect(screen.getByLabelText("Persisted model asset")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Previous asset page" })).toBeDisabled();
    unmount(); fetch.mockRestore(); confirm.mockRestore(); URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke;
  });

  it("discards a metadata restore that finishes after a context switch", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active" }], edges: [] }, nextCursor: null }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    const record = { campus_model_asset_id: "old", network_id: useWorkspaceStore.getState().networkId, model_file_name: "old.gltf" };
    let resolve!: (value: unknown) => void;
    const pending = new Promise((done) => { resolve = done; });
    mockUseCampusModelAssets.mockReturnValue({ ...queryResult({ items: [record], total: 1 }), refetch: vi.fn().mockReturnValue(pending) });
    const fetch = vi.spyOn(globalThis, "fetch");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<TwinPage />); await waitForTwinScene();
    await user.selectOptions(screen.getByLabelText("Persisted model asset"), "old");
    await user.click(screen.getByRole("button", { name: "Restore Persisted Model" }));
    act(() => useWorkspaceStore.getState().setNetworkId("other"));
    await act(async () => resolve({ data: { items: [record], total: 1 }, isError: false }));
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Persisted model asset")).toHaveValue("");
    expect(screen.getByText("model idle", { exact: true })).toBeInTheDocument();
    fetch.mockRestore(); confirm.mockRestore();
  });

  it("retains scene drafts over credential rotation and resets them on a scope change", async () => {
    spatialMocks.data = { version: 1, revision: 1, coordinate_system: { units: "m", up_axis: "y" }, objects: [] };
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [], edges: [] } }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    render(<TwinPage />);
    const editor = await screen.findByLabelText("Spatial scene JSON");
    fireEvent.change(editor, { target: { value: "unfinished draft" } });
    act(() => useAuthStore.setState({ accessToken: "rotated" }));
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue("unfinished draft");
    act(() => useWorkspaceStore.getState().setNetworkId("other"));
    expect(await screen.findByLabelText("Spatial scene JSON")).not.toHaveValue("unfinished draft");
  });

  it("warns about a partial graph and disables mapping restore and group persistence", async () => {
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active", spatial_ref_id: null }], edges: [] }, nextCursor: "more" }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    render(<TwinPage />);
    expect(await screen.findByText(/Partial topology: pagination cap reached/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore Persisted Model" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Persist Device Groups" })).toBeDisabled();
  });

  it("renders empty state", async () => {
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);

    expect(await screen.findByText("Topology graph is empty", {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it("renders error state", async () => {
    mockUseTopologyGraph.mockReturnValue(queryResult(null, { isError: true }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);

    expect(await screen.findByText("Request failed")).toBeInTheDocument();
  });

  it("renders success state and toggles overlays", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(
      queryResult({
        node: {
          device_id: "00000000-0000-0000-0000-000000000444",
          hostname: "edge-1",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
        },
        neighbours: [],
      }),
    );

    render(<TwinPage />);

    await waitForTwinScene();
    expect(screen.getByText("Congestion legend")).toBeInTheDocument();
    expect(screen.getByTestId("twin-scene")).toHaveTextContent("congestion=true");

    await user.click(screen.getByRole("button", { name: "Congestion" }));
    expect(screen.getByTestId("twin-scene")).toHaveTextContent("congestion=false");

    await user.click(screen.getByRole("button", { name: "Simulation/Intent" }));
    expect(screen.getByRole("button", { name: "Simulation/Intent" })).toHaveAttribute("aria-pressed", "false");
  });

  it("applies building/floor focus controls and forwards view state to scene", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/f01/rack-1/device-1",
            },
            {
              device_id: "00000000-0000-0000-0000-000000000445",
              hostname: "edge-2",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/f02/rack-1/device-2",
            },
            {
              device_id: "00000000-0000-0000-0000-000000000446",
              hostname: "edge-3",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-2/f01/rack-1/device-3",
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);
    await waitForTwinScene();

    await user.selectOptions(screen.getByLabelText("Twin building focus"), "campus-a:building-1");
    await user.click(screen.getByRole("button", { name: "Focus building only" }));
    await user.selectOptions(screen.getByLabelText("Twin floor focus"), "f01");
    await user.click(screen.getByRole("button", { name: "Filter selected floor" }));

    const latestTwinSceneProps = twinScenePropsSpy.mock.calls.at(-1)?.[0] as {
      buildingViewState?: {
        selectedBuildingId?: string | null;
        selectedFloorKey?: string | null;
        floorFilterEnabled?: boolean;
        visibleBuildingIds?: ReadonlySet<string>;
      };
    };

    expect(latestTwinSceneProps.buildingViewState?.selectedBuildingId).toBe("campus-a:building-1");
    expect(latestTwinSceneProps.buildingViewState?.selectedFloorKey).toBe("f01");
    expect(latestTwinSceneProps.buildingViewState?.floorFilterEnabled).toBe(true);
    expect(latestTwinSceneProps.buildingViewState?.visibleBuildingIds?.has("campus-a:building-1")).toBe(true);

    await user.click(screen.getByRole("button", { name: "Reset focus" }));
    const afterResetProps = twinScenePropsSpy.mock.calls.at(-1)?.[0] as {
      buildingViewState?: unknown;
    };
    expect(afterResetProps.buildingViewState).toBeUndefined();
  });

  it("shows device type legend and forwards live alerts to the scene", async () => {
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
            },
            {
              device_id: "00000000-0000-0000-0000-000000000445",
              hostname: "core-1",
              device_type: "router",
              status: "active",
              spatial_ref_id: "campus-a/building-1/floor-1/rack-1/device-1",
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    useLiveStore.setState((state) => ({
      ...state,
      alerts: [
        {
          event_id: "alert-1",
          event_type: "alert.generated",
          source: "telemetry",
          payload: { device_id: "00000000-0000-0000-0000-000000000444" },
        },
      ],
    }));

    render(<TwinPage />);
    await waitForTwinScene();

    expect(screen.getByText("Device type legend")).toBeInTheDocument();
    expect(screen.getByText(/Core router/i)).toBeInTheDocument();
    expect(screen.getByText(/Access switch/i)).toBeInTheDocument();

    const latestTwinSceneProps = twinScenePropsSpy.mock.calls.at(-1)?.[0] as {
      alerts?: Array<{ event_type: string; payload: Record<string, unknown> }>;
    };
    expect(latestTwinSceneProps.alerts).toHaveLength(1);
    expect(latestTwinSceneProps.alerts?.[0]?.event_type).toBe("alert.generated");
    expect(latestTwinSceneProps.alerts?.[0]?.payload.device_id).toBe("00000000-0000-0000-0000-000000000444");
  });

  it("validates invalid import files and shows import summary for valid model", async () => {
    const user = userEvent.setup({ applyAccept: false });
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: null,
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);
    await waitForTwinScene();

    const modelInput = screen.getByLabelText("Campus model file") as HTMLInputElement;

    const invalidModel = new File(["hello"], "campus.txt", { type: "text/plain" });
    await user.upload(modelInput, invalidModel);
    expect(await screen.findByText("Model file must be .glb or .gltf.")).toBeInTheDocument();

    const validModel = new File(["binary"], "campus.glb", { type: "model/gltf-binary" });
    await user.upload(modelInput, validModel);
    expect(await screen.findByText(/model GLB/i)).toBeInTheDocument();
    expect(screen.getByText(/Imported mapping is session-only/i)).toBeInTheDocument();
  });

  it("routes configure action to existing intent workflow", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(
      queryResult({
        node: {
          device_id: "00000000-0000-0000-0000-000000000444",
          hostname: "edge-1",
          device_type: "switch",
          status: "active",
          spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
        },
        neighbours: [],
      }),
    );

    render(<TwinPage />);
    await waitForTwinScene();

    await user.selectOptions(screen.getByLabelText("Inspect node"), "00000000-0000-0000-0000-000000000444");
    await user.click(screen.getByRole("button", { name: "Configure in Intent Workflow" }));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalled();
    });

    const call = navigateMock.mock.calls[0]?.[0];
    expect(typeof call).toBe("string");
    expect(call).toContain("/ops/intent?");
    expect(call).toContain("source=digital-twin");
    expect(call).toContain("action=optimize_wireless_capacity");
    expect(call).toContain("scope=");
    expect(call).toContain("constraints=");
  });

  it("persists imported mapping with existing update device API path", async () => {
    const user = userEvent.setup();
    const twinImportModule = await import("@/features/digitalTwin/twinImport");
    const parseImportSummarySpy = vi.spyOn(twinImportModule, "parseImportSummary").mockResolvedValue({
      modelFileName: "campus.glb",
      modelType: "glb",
      mappingFileName: "mapping.json",
      totalRows: 1,
      matched: 1,
      unmatched: 0,
      duplicateKeys: [],
      mappingByDeviceId: {
        "00000000-0000-0000-0000-000000000444": "campus-a/building-1/floor-1/rack-2/device-1",
      },
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
              spatial_ref_id: null,
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);
    await waitForTwinScene();

    await user.upload(screen.getByLabelText("Campus model file"), new File(["binary"], "campus.glb", { type: "model/gltf-binary" }));
    expect(await screen.findByText(/model GLB/i)).toBeInTheDocument();
    expect(parseImportSummarySpy).toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Inspect node"), "00000000-0000-0000-0000-000000000444");
    const persistButton = await screen.findByRole("button", { name: "Persist Mapping to Device" });
    expect(persistButton).toBeEnabled();

    await user.click(persistButton);

    expect(mockUpdateDeviceSpatialRefMutateAsync).toHaveBeenCalledWith({
      deviceId: "00000000-0000-0000-0000-000000000444",
      spatialRefId: "campus-a/building-1/floor-1/rack-2/device-1",
    });

    parseImportSummarySpy.mockRestore();
  });

  it("persists device groups using selected campus scope without hardcoded campus defaults", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(
      queryResult({
        data: {
          nodes: [
            {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "ap-1",
              device_type: "wireless_ap",
              status: "active",
              spatial_ref_id: "campus-a/building-1/f01/wireless/ap-1",
            },
            {
              device_id: "00000000-0000-0000-0000-000000000445",
              hostname: "sw-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/f01/access/sw-1",
            },
            {
              device_id: "00000000-0000-0000-0000-000000000446",
              hostname: "ap-2",
              device_type: "wireless_ap",
              status: "active",
              spatial_ref_id: "campus-a/building-2/f02/wireless/ap-2",
            },
          ],
          edges: [],
        },
      }),
    );
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);
    await waitForTwinScene();

    await user.selectOptions(screen.getByLabelText("Twin building focus"), "campus-a:building-1");
    await user.selectOptions(screen.getByLabelText("Twin floor focus"), "f01");
    await user.click(screen.getByRole("button", { name: "Persist Device Groups" }));

    await waitFor(() => {
      expect(mockUpsertDeviceGroupsMutateAsync).toHaveBeenCalledWith({
        replaceExisting: false,
        groups: [
          {
            group_key: "wireless-campus-a-building-1-f01",
            name: "BUILDING-1 F01 Wireless",
            group_type: "functional",
            selector: {
              site_prefix: "campus-a/building-1/f01",
              functional_group: "wireless",
            },
            device_ids: ["00000000-0000-0000-0000-000000000444"],
          },
          {
            group_key: "ops-campus-a-building-1-f01",
            name: "BUILDING-1 F01 Operations",
            group_type: "operational",
            selector: {
              site_prefix: "campus-a/building-1/f01",
            },
            device_ids: [
              "00000000-0000-0000-0000-000000000444",
              "00000000-0000-0000-0000-000000000445",
            ],
          },
        ],
      });
    });
  });

  it("parses sidecar mapping and reports duplicates/unmatched deterministically", async () => {
    const model = { name: "campus.gltf" } as File;
    const mapping = {
      name: "mapping.json",
      text: async () =>
        JSON.stringify([
          { object_name: "rack-a", device_id: "device-1", spatial_ref_id: "campus-a/b1/f1/r1/device-1" },
          { object_name: "rack-a", device_id: "device-2", spatial_ref_id: "campus-a/b1/f1/r2/device-2" },
          { object_name: "rack-c", device_id: "missing-device", spatial_ref_id: "campus-a/b1/f2/r1/device-3" },
        ]),
    } as unknown as File;

    const summary = await parseImportSummary(model, mapping, [
      { device_id: "device-1", spatial_ref_id: "campus-a/b1/f1/r1/device-1" },
      { device_id: "device-2", spatial_ref_id: "campus-a/b1/f1/r2/device-2" },
    ]);

    expect(summary.totalRows).toBe(3);
    expect(summary.matched).toBe(1);
    expect(summary.unmatched).toBe(1);
    expect(summary.duplicateKeys).toEqual(["rack-a"]);
    expect(summary.mappingByDeviceId["device-1"]).toBe("campus-a/b1/f1/r1/device-1");
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
const mockUseAlertsQuery = vi.fn();

vi.mock("@/features/reliability/hooks", () => ({
  useAlertsQuery: (...args: unknown[]) => mockUseAlertsQuery(...args),
}));

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
const twinSceneMounts = vi.fn();

// jsdom has no WebGL: the page tests exercise the 3D path (TwinScene is mocked below);
// the 2D fallback is covered by TwinViewport.test.tsx.
vi.mock("@/features/digitalTwin/webglSupport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/digitalTwin/webglSupport")>()),
  detectWebGLSupport: () => true,
}));

vi.mock("@/features/digitalTwin/TwinScene", async () => {
  const { useEffect } = await vi.importActual<typeof import("react")>("react");
  return {
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
      useEffect(() => { twinSceneMounts(); }, []);
      return (
      <div data-testid="twin-scene">
        scene nodes={props.nodes.length} links={props.links.length} overlays={props.overlays.length} congestion={String(props.layers.showCongestion)}
      </div>
      );
    },
  };
});

/** Keyboard selection through the Inspect node combobox (replaces the old 12,800-option select). */
async function inspectNode(user: ReturnType<typeof userEvent.setup>, deviceId: string) {
  const input = screen.getByLabelText("Inspect node");
  await user.clear(input);
  await user.type(input, deviceId);
  await user.keyboard("{Enter}");
  expect(input).toHaveAttribute("data-selected-node-id", deviceId);
}

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

/** Minimal valid GLB (JSON chunk only) so session imports pass structural validation. */
function glbFile(name = "campus.glb", document: Record<string, unknown> = { asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ name: "campus" }] }) {
  const json = JSON.stringify(document);
  const data = new TextEncoder().encode(json.padEnd(Math.ceil(json.length / 4) * 4, " "));
  const buffer = new ArrayBuffer(20 + data.length);
  const view = new DataView(buffer);
  [0x46546c67, 2, buffer.byteLength, data.length, 0x4e4f534a].forEach((value, index) => view.setUint32(index * 4, value, true));
  new Uint8Array(buffer, 20).set(data);
  return new File([buffer], name, { type: "model/gltf-binary" });
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
    twinSceneMounts.mockReset();
    mockUseCampusBuildings.mockReset();
    mockUseAlertsQuery.mockReset();
    mockUseAlertsQuery.mockReturnValue(queryResult({ items: [], total: 0, status_counts: {} }));
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

  it("renders loading state as an overlay over the mounted 3D view", async () => {
    mockUseTopologyGraph.mockReturnValue(queryResult(null, { isLoading: true }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);

    expect(await screen.findByText("Loading topology", {}, { timeout: 5000 })).toBeInTheDocument();
    // The Canvas lives outside the query state: loading never unmounts the view.
    expect(screen.getByTestId("twin-scene")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Digital twin view" })).toHaveAttribute("aria-busy", "true");
  });

  it("keeps one 3D view mounted across loading, error, retry and data states", async () => {
    const refetch = vi.fn().mockResolvedValue({ data: undefined, isError: true });
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    mockUseTopologyGraph.mockReturnValue(queryResult(null, { isLoading: true }));
    const { rerender } = render(<TwinPage />);
    await waitForTwinScene();
    mockUseTopologyGraph.mockReturnValue({ ...queryResult(null, { isError: true, refetch }), error: new Error("graph down") });
    rerender(<TwinPage />);
    const view = screen.getByRole("group", { name: "Digital twin view" });
    expect(await within(view).findByRole("alert")).toHaveTextContent("Topology request failed");
    expect(within(view).getByText(/graph down/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry loading topology" }));
    expect(refetch).toHaveBeenCalledTimes(1);
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active", spatial_ref_id: null }], edges: [] }, nextCursor: null }));
    rerender(<TwinPage />);
    await waitFor(() => expect(screen.queryByText("Topology request failed")).not.toBeInTheDocument());
    expect(screen.getByTestId("twin-scene")).toHaveTextContent("scene nodes=1");
    expect(twinSceneMounts).toHaveBeenCalledTimes(1);
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
    await inspectNode(user, id);
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

    expect(await screen.findByText("Topology request failed", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading topology" })).toBeEnabled();
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

    const latestTwinSceneProps = twinScenePropsSpy.mock.calls.at(-1)?.[0] as { alertingDeviceIds?: ReadonlySet<string> };
    expect([...(latestTwinSceneProps.alertingDeviceIds ?? [])]).toEqual(["00000000-0000-0000-0000-000000000444"]);
    expect(mockUseAlertsQuery).toHaveBeenCalledWith("token-1", expect.objectContaining({ status: "active", networkId: "00000000-0000-0000-0000-000000000333" }), true);
  });

  it("uses the REST snapshot of active backend alerts as the authoritative device severity", async () => {
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [
      { device_id: "00000000-0000-0000-0000-000000000444", hostname: "edge-1", device_type: "switch", status: "active", spatial_ref_id: null },
      { device_id: "00000000-0000-0000-0000-000000000445", hostname: "edge-2", device_type: "switch", status: "active", spatial_ref_id: null },
    ], edges: [] } }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    mockUseAlertsQuery.mockReturnValue(queryResult({ items: [
      { alert_id: "a-1", alert_key: "measured:k1", source: "telemetry", status: "active", severity: "warning", correlation_id: "c", updated_at: "2026-09-24T00:00:00Z",
        payload: { device_id: "00000000-0000-0000-0000-000000000445", metric: "latency_ms", value: 130, unit: "ms", rule: { breach: 100, recover: 70 } } },
    ], total: 1, status_counts: { active: 1 } }));
    useLiveStore.setState({ alerts: [{ event_id: "e", event_type: "alert.resolved", source: "telemetry", timestamp: "2026-09-23T00:00:00Z",
      payload: { alert_id: "a-1", device_id: "00000000-0000-0000-0000-000000000445" } }] });
    render(<TwinPage />);
    await waitForTwinScene();
    const props = twinScenePropsSpy.mock.calls.at(-1)?.[0] as { alertingDeviceIds?: ReadonlySet<string> };
    // The older live resolution does not override the newer REST record.
    expect([...(props.alertingDeviceIds ?? [])]).toEqual(["00000000-0000-0000-0000-000000000445"]);
    expect(screen.getByText("1 device with active backend alerts.")).toBeInTheDocument();
    expect(screen.getAllByText(/Visual heuristic/).length).toBeGreaterThan(0);
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

    const modelInput = screen.getByLabelText("Campus model file");

    const invalidModel = new File(["hello"], "campus.txt", { type: "text/plain" });
    await user.upload(modelInput, invalidModel);
    expect(await screen.findByText("Model file must be .glb or .gltf.")).toBeInTheDocument();

    const corruptModel = new File(["binary"], "campus.glb", { type: "model/gltf-binary" });
    await user.upload(modelInput, corruptModel);
    expect(await screen.findByText("Invalid GLB version or declared length.")).toBeInTheDocument();

    await user.upload(modelInput, glbFile());
    expect(await screen.findByText(/model GLB/i)).toBeInTheDocument();
    expect(screen.getByText(/Imported mapping is session-only/i)).toBeInTheDocument();
  });

  it("rejects a session glTF with an absolute external URI before creating an object URL", async () => {
    const user = userEvent.setup({ applyAccept: false });
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active", spatial_ref_id: null }], edges: [] } }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    const create = vi.fn().mockReturnValue("blob:never");
    const previousCreate = URL.createObjectURL;
    URL.createObjectURL = create;
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<TwinPage />);
    await waitForTwinScene();
    const external = new File([JSON.stringify({ asset: { version: "2.0" }, buffers: [{ uri: "https://attacker.example/model.bin", byteLength: 4 }] })], "campus.gltf", { type: "model/gltf+json" });
    await user.upload(screen.getByLabelText("Campus model file"), external);
    expect(await screen.findByText("Model must be self-contained; external resource URIs are not supported.")).toBeInTheDocument();
    const relative = new File([JSON.stringify({ asset: { version: "2.0" }, images: [{ uri: "texture.png" }] })], "campus.gltf", { type: "model/gltf+json" });
    await user.upload(screen.getByLabelText("Campus model file"), relative);
    await waitFor(() => expect(screen.getAllByText("Model must be self-contained; external resource URIs are not supported.")).toHaveLength(1));
    const oversized = new File([new Uint8Array(8 * 1024 * 1024 + 1)], "big.glb", { type: "model/gltf-binary" });
    await user.upload(screen.getByLabelText("Campus model file"), oversized);
    expect(await screen.findByText("Model must be between 1 byte and 8 MiB.")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(twinScenePropsSpy.mock.calls.at(-1)?.[0].importedModelUrl).toBeNull();
    expect(screen.queryByText(/model GLTF/i)).not.toBeInTheDocument();
    URL.createObjectURL = previousCreate;
    fetchSpy.mockRestore();
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

    await inspectNode(user, "00000000-0000-0000-0000-000000000444");
    await user.click(screen.getByRole("button", { name: "Configure in Intent Workflow" }));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalled();
    });

    const [target, options] = navigateMock.mock.calls[0] ?? [];
    // Router state, never the URL (ADR-028 intent handoff): nothing lands in history or referrers.
    expect(target).toBe("/ops/intent");
    const handoff = options.state.intentHandoff;
    expect(handoff.source).toBe("digital-twin");
    // The visual heuristic never selects an action or travels as a policy.
    expect(handoff.action).toBeNull();
    const scope = JSON.parse(handoff.scopeJson);
    expect(scope).toEqual({ source: "digital_twin", device_id: "00000000-0000-0000-0000-000000000444",
      spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1", backend_alerts: [] });
    expect(handoff.scopeJson).not.toMatch(/policy|congestion|heuristic|score/);
    expect(handoff.constraintsJson).toContain("simulation_required");
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

    await user.upload(screen.getByLabelText("Campus model file"), glbFile());
    expect(await screen.findByText(/model GLB/i)).toBeInTheDocument();
    expect(parseImportSummarySpy).toHaveBeenCalled();

    await inspectNode(user, "00000000-0000-0000-0000-000000000444");
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
    const trigger = screen.getByRole("button", { name: "Persist Device Groups" });
    await user.click(trigger);

    // Preview first: nothing is written until the operator confirms.
    const dialog = await screen.findByRole("dialog", { name: "Review device groups before persisting" });
    expect(mockUpsertDeviceGroupsMutateAsync).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("site_prefix campus-a/building-1/f01");
    expect(dialog).toHaveTextContent("2 devices currently in scope");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm and persist groups" }));

    await waitFor(() => {
      expect(mockUpsertDeviceGroupsMutateAsync).toHaveBeenCalledWith({
        replaceExisting: false,
        groups: [
          {
            group_key: "wireless-campus-a-building-1-f01",
            name: "BUILDING-1 F01 Wireless",
            group_type: "functional",
            selector: {
              functional_group: "wireless",
              site_prefix: "campus-a/building-1/f01",
            },
            // Membership is resolved by the server's classifier, never in the browser.
            device_ids: [],
          },
          {
            group_key: "ops-campus-a-building-1-f01",
            name: "BUILDING-1 F01 Operations",
            group_type: "operational",
            selector: {
              site_prefix: "campus-a/building-1/f01",
            },
            device_ids: [],
          },
        ],
      });
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sends expected_updated_at and reloads with a diff on 409 DEVICE_GROUP_CONFLICT", async () => {
    const user = userEvent.setup();
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [
      { device_id: "00000000-0000-0000-0000-000000000444", hostname: "ap-1", device_type: "wireless_ap", status: "active", spatial_ref_id: "campus-a/building-1/f01/wireless/ap-1" },
    ], edges: [] } }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    const existing = { device_group_id: "g1", network_id: "n", group_key: "wireless-campus-a-building-1-f01", name: "BUILDING-1 F01 Wireless", group_type: "functional",
      description: null, selector: { functional_group: "wireless", site_prefix: "campus-a/building-1/f01" }, device_ids: [], created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-02T00:00:00Z" };
    const concurrent = { ...existing, updated_at: "2026-09-03T00:00:00Z", name: "Renamed elsewhere", device_ids: ["00000000-0000-0000-0000-000000000444"] };
    const refetch = vi.fn().mockResolvedValue({ data: { items: [concurrent], total: 1 }, isError: false });
    mockUseDeviceGroups.mockReturnValue({ ...queryResult({ items: [existing], total: 1 }), refetch });
    const { ApiClientError } = await import("@/shared/lib/errors");
    mockUpsertDeviceGroupsMutateAsync.mockRejectedValueOnce(new ApiClientError("Device group changed", "DEVICE_GROUP_CONFLICT", 409)).mockResolvedValueOnce({ items: [], total: 0 });
    render(<TwinPage />);
    await waitForTwinScene();
    await user.click(screen.getByRole("button", { name: "Persist Device Groups" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm and persist groups" }));
    expect(mockUpsertDeviceGroupsMutateAsync.mock.calls[0][0].groups[0]).toMatchObject({ group_key: existing.group_key, expected_updated_at: "2026-09-02T00:00:00Z" });
    expect(mockUpsertDeviceGroupsMutateAsync.mock.calls[0][0].groups[1]).not.toHaveProperty("expected_updated_at");
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/changed on the server since they were read/)).toBeInTheDocument();
    expect(within(dialog).getByRole("list", { name: "Server changes since last read" })).toHaveTextContent(
      "wireless-campus-a-building-1-f01: modified (name, device_ids) · updated 2026-09-02T00:00:00Z → 2026-09-03T00:00:00Z · members 0 → 1");
    expect(refetch).toHaveBeenCalledTimes(1);
    await user.click(within(dialog).getByRole("button", { name: "Confirm and persist groups" }));
    await waitFor(() => expect(mockUpsertDeviceGroupsMutateAsync).toHaveBeenCalledTimes(2));
    expect(mockUpsertDeviceGroupsMutateAsync.mock.calls[1][0].groups[0].expected_updated_at).toBe("2026-09-03T00:00:00Z");
  });

  it("shows explicit error and retry states instead of zero counts for persisted groups", async () => {
    mockUseTopologyGraph.mockReturnValue(queryResult({ data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active", spatial_ref_id: null }], edges: [] } }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));
    const retryGroups = vi.fn().mockResolvedValue({ data: undefined, isError: true });
    mockUseDeviceGroups.mockReturnValue({ ...queryResult(null, { isError: true }), error: new Error("groups down"), refetch: retryGroups });
    render(<TwinPage />);
    await waitForTwinScene();
    const groups = screen.getByRole("region", { name: "Device groups" });
    expect(within(groups).getByRole("alert")).toHaveTextContent("Persisted device groups unavailable: groups down");
    expect(within(groups).queryByText(/persisted \d/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Persist Device Groups" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Retry loading groups" }));
    expect(retryGroups).toHaveBeenCalled();
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

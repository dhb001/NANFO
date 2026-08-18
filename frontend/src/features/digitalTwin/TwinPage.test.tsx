import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TwinPage } from "@/features/digitalTwin/TwinPage";
import { parseImportSummary } from "@/features/digitalTwin/twinImport";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";

const mockUseTopologyGraph = vi.fn();
const mockUseTopologyNode = vi.fn();
const mockUpdateDeviceSpatialRefMutateAsync = vi.fn();

const navigateMock = vi.fn();

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
}));

vi.mock("@/features/digitalTwin/TwinScene", () => ({
  TwinScene: (props: { layers: Record<string, boolean>; nodes: unknown[]; links: unknown[]; overlays: unknown[] }) => (
    <div data-testid="twin-scene">
      scene nodes={props.nodes.length} links={props.links.length} overlays={props.overlays.length} congestion={String(props.layers.showCongestion)}
    </div>
  ),
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
    refetch: options?.refetch ?? vi.fn(),
  };
}

async function waitForTwinScene() {
  return screen.findByTestId("twin-scene");
}

describe("TwinPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();

    useAuthStore.setState({
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
          observed_at: "2026-08-18T08:00:00Z",
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
  });

  it("renders loading state", () => {
    mockUseTopologyGraph.mockReturnValue(queryResult(null, { isLoading: true }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);

    expect(screen.getByText("Loading")).toBeInTheDocument();
  });

  it("renders empty state", () => {
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

    expect(screen.getByText("Topology graph is empty")).toBeInTheDocument();
  });

  it("renders error state", () => {
    mockUseTopologyGraph.mockReturnValue(queryResult(null, { isError: true }));
    mockUseTopologyNode.mockReturnValue(queryResult(null));

    render(<TwinPage />);

    expect(screen.getByText("Request failed")).toBeInTheDocument();
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
    expect(screen.getByText(/Imported mapping is kept in local session state only/i)).toBeInTheDocument();
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

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLiveStore } from "@/features/realtime/store";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { LiveSceneDeltasPanel, MAX_DELTA_CARDS, TwinChannelBadges } from "./LiveSceneDeltasPanel";
import { ModelAssetPanel } from "./ModelAssetPanel";
import { TwinDisclosure } from "./TwinDisclosure";
import { TwinLayerToolbar } from "./TwinLayerToolbar";
import { CongestionLegendCard, SpatialMappingCard } from "./TwinLegendCards";
import type { TwinOverlayObject } from "./sceneAdapter";
import { DEFAULT_LAYERS } from "./twinViewState";
import type { ModelAssetWorkflow } from "./useModelAssetWorkflow";

const overlay = (id: string, overrides: Partial<TwinOverlayObject> = {}): TwinOverlayObject => ({
  id, objectType: "simulation_state", status: null, state: null, simulationId: null, intentId: null, spatialRefId: null, x: 0, y: 0, z: 0, ...overrides,
});
const alerts = (overrides: Partial<{ isLoading: boolean; isError: boolean; error: unknown; data: unknown }> = {}) => ({
  isLoading: false, isError: false, error: null, data: { items: [] }, refetch: vi.fn(), ...overrides,
});

describe("Twin panels", () => {
  beforeEach(() => {
    useAuthStore.setState({ profile: operatorProfile, accessToken: "token-1" });
  });

  it("toggles layers with aria-pressed and keeps the model layer unavailable until a model exists", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const { rerender } = render(<TwinLayerToolbar layers={{ ...DEFAULT_LAYERS, showCongestion: false }} modelAvailable={false} onToggle={onToggle} />);
    const group = screen.getByRole("group", { name: "Digital twin layer controls" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent)).toEqual(["Links", "Labels", "Congestion", "Simulation/Intent", "Campus model", "OSM buildings"]);
    expect(screen.getByRole("button", { name: "Congestion" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Links" })).toHaveAttribute("aria-pressed", "true");
    const model = screen.getByRole("button", { name: "Campus model" });
    expect(model).toBeDisabled();
    expect(model).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "Congestion" }));
    expect(onToggle).toHaveBeenCalledWith("showCongestion");
    rerender(<TwinLayerToolbar layers={DEFAULT_LAYERS} modelAvailable onToggle={onToggle} />);
    expect(screen.getByRole("button", { name: "Campus model" })).toHaveAttribute("aria-pressed", "true");
  });

  it("states backend alerts as authoritative and never reports a zero while alerts load or fail", async () => {
    const user = userEvent.setup();
    const failed = alerts({ isError: true, error: new Error("alerts down"), data: undefined });
    const { rerender } = render(<CongestionLegendCard alertsQuery={alerts({ isLoading: true, data: undefined })} alertsEnabled alertingCount={0} />);
    const card = screen.getByRole("region", { name: "Congestion legend" });
    expect(within(card).getByRole("status")).toHaveTextContent("Loading backend alerts…");
    expect(card).not.toHaveTextContent(/0 devices/);
    rerender(<CongestionLegendCard alertsQuery={failed} alertsEnabled alertingCount={0} />);
    expect(within(card).getByRole("alert")).toHaveTextContent("Backend alerts unavailable: alerts down Alert states may be incomplete.");
    await user.click(within(card).getByRole("button", { name: "Retry loading alerts" }));
    expect(failed.refetch).toHaveBeenCalledTimes(1);
    rerender(<CongestionLegendCard alertsQuery={alerts()} alertsEnabled alertingCount={2} />);
    expect(card).toHaveTextContent("2 devices with active backend alerts.");
    expect(card).toHaveTextContent("Link utilization (link_utilization_percent): breach ≥ 85 %, recovery < 70 %");
    expect(card).toHaveTextContent("Visual heuristic (ring colour, not an alert, never sent as policy)");
    expect(card).toHaveTextContent("“ALERT” label");
    rerender(<CongestionLegendCard alertsQuery={alerts({ data: undefined })} alertsEnabled={false} alertingCount={0} />);
    expect(card).toHaveTextContent("needs the read:telemetry permission");
  });

  it("shows placement counts only once topology has loaded", () => {
    const nodes = [{ id: "a", hostname: "a", type: "switch", status: "active", x: 0, y: 0, z: 0, spatialRefId: null, placementSource: "canonical" as const }];
    const { rerender } = render(<SpatialMappingCard nodes={[]} ready={false} />);
    expect(screen.getByRole("region", { name: "Spatial mapping state" })).toHaveTextContent("Placement counts appear once topology has loaded.");
    rerender(<SpatialMappingCard nodes={nodes} ready />);
    expect(screen.getByRole("region", { name: "Spatial mapping state" })).toHaveTextContent("1 canonical device placement.");
  });

  it("lists the newest scene deltas with explicit lifecycle tones and reconciliation state", () => {
    useLiveStore.setState({ topologyStatus: "open", digitalTwinStatus: "connecting", sceneObjectLastSeen: { "simulation:1": Date.parse("2026-09-24T10:00:00Z") }, sceneObjectAvailability: { "simulation:1": "reconciled" }, sceneReconciliation: null });
    render(<>
      <TwinChannelBadges />
      <LiveSceneDeltasPanel overlays={[
        overlay("simulation:1", { status: "running", spatialRefId: "campus-a/building-1" }),
        overlay("intent:2", { objectType: "intent_state", status: "execution_failed" }),
        ...Array.from({ length: 12 }, (_, index) => overlay(`extra:${index}`)),
      ]} />
    </>);
    expect(screen.getByText("topology open")).toHaveClass("badge--ok");
    expect(screen.getByText("digital twin connecting")).toHaveClass("badge--warn");
    const region = screen.getByRole("region", { name: "Live Scene Deltas" });
    expect(within(region).getAllByRole("listitem")).toHaveLength(MAX_DELTA_CARDS);
    expect(within(region).getByText("running")).toHaveClass("badge--info");
    expect(within(region).getByText("execution_failed")).toHaveClass("badge--danger");
    expect(within(region).getByText(/Detail reconciliation: reconciled/)).toBeInTheDocument();
    expect(within(region).getByText("intent:2").closest("li")).toHaveTextContent("Last observed: unavailable. Detail reconciliation: stale.");
    expect(within(region).getByText("campus-a/building-1")).toBeInTheDocument();
    expect(within(region).getByRole("status")).toHaveTextContent("Partial known-object view only");
  });

  it("shows explicit empty state when no scene deltas were observed", () => {
    render(<LiveSceneDeltasPanel overlays={[]} />);
    expect(screen.getByText("No scene deltas observed yet.")).toBeInTheDocument();
  });

  it("never shows a zero asset count while the model asset list loads or fails", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    const model = (assetsQuery: Record<string, unknown>) => ({
      assetsQuery: { isFetching: false, isLoading: false, isError: false, data: undefined, refetch, ...assetsQuery }, assetPage: 2, setAssetPage: vi.fn(),
      selectedAsset: undefined, visibleAssets: [], status: "idle", statusMessage: null, isImporting: false, isPersisting: false, importedModelUrl: null,
      registration: null, canPersist: false, canRestore: false, persist: vi.fn(), restore: vi.fn(), applyRegistration: vi.fn(),
    }) as unknown as ModelAssetWorkflow;
    const { rerender } = render(<ModelAssetPanel model={model({ isLoading: true, isFetching: true })} layerVisible />);
    const region = screen.getByRole("region", { name: "Imported model state" });
    expect(region).toHaveTextContent("Asset page 2 · loading asset count");
    expect(region).not.toHaveTextContent(/persisted assets 0/);
    rerender(<ModelAssetPanel model={model({ isError: true, error: new Error("assets down") })} layerVisible />);
    expect(within(region).getByRole("alert")).toHaveTextContent("Model asset list unavailable: assets down Use Reload model assets to retry.");
    expect(region).toHaveTextContent("Asset page 2 · asset count unavailable");
    await user.click(within(region).getByRole("button", { name: "Reload model assets" }));
    expect(refetch).toHaveBeenCalledTimes(1);
    rerender(<ModelAssetPanel model={model({ data: { items: [], total: 21 } })} layerVisible={false} />);
    expect(within(region).getByText("Asset page 2 · 21 assets")).toBeInTheDocument();
    expect(within(region).getByText("persisted assets 21")).toHaveClass("badge--ok");
    expect(within(region).getByText("model idle")).toHaveClass("badge--neutral");
    expect(within(region).getByText("layer hidden")).toBeInTheDocument();
  });

  it("discloses content with aria-expanded/aria-controls and can keep drafts mounted while hidden", async () => {
    const user = userEvent.setup();
    render(<>
      <TwinDisclosure label="Show measured probe paths" openLabel="Hide measured probe paths"><input aria-label="probe draft" /></TwinDisclosure>
      <TwinDisclosure label="Custom device groups" keepMounted><input aria-label="group draft" /></TwinDisclosure>
    </>);
    const probes = screen.getByRole("button", { name: "Show measured probe paths" });
    expect(probes).toHaveAttribute("aria-expanded", "false");
    expect(probes).not.toHaveAttribute("aria-controls");
    await user.click(probes);
    expect(screen.getByRole("button", { name: "Hide measured probe paths" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Hide measured probe paths" })).toHaveAttribute("aria-controls", screen.getByLabelText("probe draft").parentElement?.id);
    const groups = screen.getByRole("button", { name: "Custom device groups" });
    await user.click(groups);
    await user.type(screen.getByLabelText("group draft"), "survey");
    await user.click(groups);
    expect(groups).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("group draft")).not.toBeVisible();
    await user.click(groups);
    expect(screen.getByLabelText("group draft")).toHaveValue("survey");
    await user.click(screen.getByRole("button", { name: "Hide measured probe paths" }));
    expect(screen.queryByLabelText("probe draft")).not.toBeInTheDocument();
  });
});

import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { operatorProfile } from "@/test/profile";
import { TwinInspectorPanel } from "./TwinInspectorPanel";
import { NEUTRAL_CONGESTION, type TwinNode } from "./sceneAdapter";
import type { DeviceAlertSummary } from "./twinSeverity";

const mocks = vi.hoisted(() => ({ navigate: vi.fn(), mutateAsync: vi.fn(), nodeQuery: vi.fn() }));

vi.mock("react-router-dom", () => ({ useNavigate: () => mocks.navigate }));
vi.mock("@/features/networks/hooks", () => ({ useUpdateDeviceSpatialRef: () => ({ mutateAsync: mocks.mutateAsync, isPending: false }) }));
vi.mock("@/features/topology/hooks", () => ({ useTopologyNode: (...args: unknown[]) => mocks.nodeQuery(...args) }));

const edge: TwinNode = { id: "dev-1", hostname: "edge-1", type: "switch", status: "offline", x: 1, y: 2, z: 3, spatialRefId: "campus-a/building-1/f01/sw", persistedSpatialRefId: "campus-a/building-1/f01/sw" };
const core: TwinNode = { id: "dev-2", hostname: "core-1", type: "router", status: "active", x: 0, y: 0, z: 0, spatialRefId: null, persistedSpatialRefId: null };
const activeAlert: DeviceAlertSummary = { deviceId: "dev-1", status: "active", alerts: [{ key: "a-1", alertId: "a-1", alertKey: "k", deviceId: "dev-1", status: "active", severity: "warning", metric: "latency_ms", value: 130, unit: "ms", breach: 100, recover: 70, origin: "rest" }] };

function Harness({ nodes = [edge, core], sessionRefs = {}, alerts }: { nodes?: TwinNode[]; sessionRefs?: Record<string, string>; alerts?: DeviceAlertSummary }) {
  const [selected, setSelected] = useState<string | null>(null);
  const node = nodes.find((item) => item.id === selected) ?? null;
  return (
    <TwinInspectorPanel token="token-1" networkId="net-1" nodes={nodes} selectedNode={node} selectedNodeId={selected} onSelectNode={setSelected}
      congestion={NEUTRAL_CONGESTION} alerts={selected === "dev-1" ? alerts : undefined} sessionRef={(selected ? sessionRefs[selected] : undefined) ?? null} />
  );
}

async function pick(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByRole("combobox", { name: "Inspect node" }), text);
  await user.keyboard("{Enter}");
}

describe("TwinInspectorPanel", () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
    mocks.mutateAsync.mockReset().mockResolvedValue({});
    mocks.nodeQuery.mockReset().mockReturnValue({ isLoading: false, isError: false, data: undefined, refetch: vi.fn() });
    useAuthStore.setState({ profile: operatorProfile, accessToken: "token-1" });
    useUiStore.setState({ toasts: [] });
  });

  it("starts with an explicit empty state and a keyboard node picker", () => {
    render(<Harness />);
    expect(screen.getByRole("region", { name: "Inspector" })).toHaveTextContent("Select a node");
    expect(screen.getByRole("combobox", { name: "Inspect node" })).toHaveAttribute("aria-expanded", "false");
    expect(mocks.nodeQuery).toHaveBeenLastCalledWith("token-1", null);
  });

  it("shows identity, explicit status tones, backend alert text and the labelled visual heuristic for the picked node", async () => {
    const user = userEvent.setup();
    mocks.nodeQuery.mockImplementation((_token: string, id: string | null) => ({ isLoading: false, isError: false, refetch: vi.fn(),
      data: id ? { node: {}, neighbours: [{ device_id: "dev-2", hostname: "core-1", direction: "outbound" }] } : undefined }));
    render(<Harness alerts={activeAlert} />);
    await pick(user, "edge");
    const region = screen.getByRole("region", { name: "Inspector" });
    expect(within(region).getByText("edge-1", { selector: "strong" })).toBeInTheDocument();
    expect(within(region).getByText("offline")).toHaveClass("badge--warn");
    expect(within(region).getByText("1 active backend alert")).toHaveClass("badge--danger");
    expect(within(region).getByText("spatial_ref_id: campus-a/building-1/f01/sw")).toBeInTheDocument();
    expect(within(region).getByText("Position: schematic fallback · (1.00, 2.00, 3.00) m")).toBeInTheDocument();
    expect(within(region).getByText("persisted")).toHaveClass("badge--ok");
    expect(within(region).getByText("Visual heuristic: no current detector-covered sample (not an alert)")).toBeInTheDocument();
    expect(within(region).getByRole("list", { name: "Topology neighbours" })).toHaveTextContent("core-1");
    expect(mocks.nodeQuery).toHaveBeenLastCalledWith("token-1", "dev-1");
    // No session mapping: nothing to persist.
    expect(within(region).queryByRole("button", { name: "Persist Mapping to Device" })).not.toBeInTheDocument();
  });

  it("persists a session mapping only when it differs from the persisted reference", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Harness sessionRefs={{ "dev-1": "campus-a/building-1/f01/sw" }} />);
    await pick(user, "edge");
    expect(screen.getByRole("button", { name: "Persist Mapping to Device" })).toBeDisabled();
    unmount();
    const mapped = { ...core, spatialRefId: "campus-a/building-2/f02/core" };
    render(<Harness nodes={[edge, mapped]} sessionRefs={{ "dev-2": "campus-a/building-2/f02/core" }} />);
    await pick(user, "core");
    expect(screen.getByText("not persisted")).toHaveClass("badge--warn");
    expect(screen.getByText("session import")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Persist Mapping to Device" }));
    expect(mocks.mutateAsync).toHaveBeenCalledWith({ deviceId: "dev-2", spatialRefId: "campus-a/building-2/f02/core" });
    await waitFor(() => expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ tone: "ok", title: "Spatial mapping persisted" }));
  });

  it("reports a failed mapping persist without losing the selection", async () => {
    const user = userEvent.setup();
    mocks.mutateAsync.mockRejectedValue(new Error("device changed"));
    render(<Harness nodes={[edge, { ...core, spatialRefId: "campus-a/b/f/x" }]} sessionRefs={{ "dev-2": "campus-a/b/f/x" }} />);
    await pick(user, "core");
    await user.click(screen.getByRole("button", { name: "Persist Mapping to Device" }));
    await waitFor(() => expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ tone: "danger", title: "Spatial mapping persist failed", description: "device changed" }));
    expect(screen.getByRole("combobox", { name: "Inspect node" })).toHaveAttribute("data-selected-node-id", "dev-2");
  });

  it("hands off to the intent workflow with the persisted reference and backend alert refs only", async () => {
    const user = userEvent.setup();
    render(<Harness alerts={activeAlert} />);
    await pick(user, "dev-1");
    await user.click(screen.getByRole("button", { name: "Configure in Intent Workflow" }));
    const [target, options] = mocks.navigate.mock.calls[0] ?? [];
    expect(target).toBe("/ops/intent");
    const scope = JSON.parse(options.state.intentHandoff.scopeJson);
    expect(options.state.intentHandoff).toMatchObject({ source: "digital-twin", action: null });
    expect(scope).toEqual({ source: "digital_twin", device_id: "dev-1", spatial_ref_id: "campus-a/building-1/f01/sw",
      backend_alerts: [{ alert_id: "a-1", alert_key: "k", status: "active", severity: "warning", metric: "latency_ms" }] });
  });
});

import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TwinSceneProps } from "./TwinScene";
import { TwinViewport } from "./TwinViewport";
import { READY_STATUS, resolveViewportStatus } from "./twinViewportStatus";

const control = vi.hoisted(() => ({ webgl: true, throwOnRender: null as Error | null, mounts: 0 }));

vi.mock("./webglSupport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./webglSupport")>()),
  detectWebGLSupport: () => control.webgl,
}));

vi.mock("./TwinScene", () => ({
  TwinScene: (props: TwinSceneProps) => {
    useEffect(() => { control.mounts += 1; }, []);
    if (control.throwOnRender) throw control.throwOnRender;
    return <div data-testid="scene">3D nodes={props.nodes.length}</div>;
  },
}));

const node = (id: string, hostname: string, x: number, z: number) => ({ id, hostname, type: "switch", status: "active", x, y: 0, z, spatialRefId: null });

function sceneProps(overrides: Partial<TwinSceneProps> = {}): TwinSceneProps {
  return {
    nodes: [node("a", "edge-a", 0, 0), node("b", "edge-b", 10, 5), node("c", "core-c", -4, 2)],
    links: [{ id: "a-b", source: [0, 0, 0], target: [10, 0, 5], sourceId: "a", targetId: "b", edgeType: "l2", metadata: {} }],
    overlays: [],
    selectedNodeId: null,
    onSelectNode: vi.fn(),
    reducedMotion: false,
    layers: { showLinks: true, showLabels: true, showCongestion: true, showOverlays: true, showModel: true },
    alertingDeviceIds: new Set(["b"]),
    ...overrides,
  };
}

describe("TwinViewport", () => {
  beforeEach(() => {
    control.webgl = true;
    control.throwOnRender = null;
    control.mounts = 0;
    // Boundary tests throw on purpose: keep React's and jsdom's error reports out of the output.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const swallow = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", swallow);
    return () => {
      window.removeEventListener("error", swallow);
      errorSpy.mockRestore();
    };
  });

  it("overlays loading, error and empty states on one mounted scene", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const scene = sceneProps();
    const status = (input: Partial<Parameters<typeof resolveViewportStatus>[0]>) =>
      resolveViewportStatus({ networkSelected: true, isLoading: false, isError: false, error: null, hasData: true, hasContent: true, ...input });
    const { rerender } = render(<TwinViewport status={status({ isLoading: true, hasData: false })} onRetry={onRetry} scene={scene} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading topology");
    expect(screen.getByRole("group", { name: "Digital twin view" })).toHaveAttribute("aria-busy", "true");
    rerender(<TwinViewport status={status({ isError: true, error: new Error("graph down") })} onRetry={onRetry} scene={scene} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Topology request failed");
    expect(screen.getByRole("alert")).toHaveTextContent("graph down The last loaded topology stays visible.");
    await user.click(screen.getByRole("button", { name: "Retry loading topology" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<TwinViewport status={status({ hasContent: false })} onRetry={onRetry} scene={scene} />);
    expect(screen.getByRole("status")).toHaveTextContent("Topology graph is empty");
    rerender(<TwinViewport status={READY_STATUS} onRetry={onRetry} scene={scene} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByTestId("scene")).toHaveTextContent("3D nodes=3");
    expect(control.mounts).toBe(1);
  });

  it("shows the 2D plan with keyboard-reachable alert selection when WebGL is unavailable", async () => {
    const user = userEvent.setup();
    control.webgl = false;
    const scene = sceneProps();
    render(<TwinViewport status={READY_STATUS} onRetry={vi.fn()} scene={scene} />);
    expect(screen.queryByTestId("scene")).not.toBeInTheDocument();
    const plan = screen.getByRole("region", { name: "2D plan view" });
    expect(within(plan).getByRole("alert")).toHaveTextContent("3D view unavailable");
    expect(within(plan).getByRole("alert")).toHaveTextContent("cannot create a WebGL context");
    expect(within(plan).getByRole("img")).toHaveAccessibleName(/2D plan of 3 devices and 1 links; 1 with active backend alerts/);
    const alerts = within(plan).getByRole("list", { name: "Devices with active backend alerts" });
    await user.click(within(alerts).getByRole("button", { name: "ALERT edge-b" }));
    expect(scene.onSelectNode).toHaveBeenCalledWith("b");
  });

  it("contains a renderer crash in the Canvas boundary, falls back to 2D, and retries 3D", async () => {
    const user = userEvent.setup();
    control.throwOnRender = new Error("Error creating WebGL context.");
    const onImportedModelStatusChange = vi.fn();
    render(<div><p>Inspector stays</p><TwinViewport status={READY_STATUS} onRetry={vi.fn()} scene={sceneProps({ importedModelUrl: "blob:model", onImportedModelStatusChange })} /></div>);
    expect(await screen.findByRole("region", { name: "2D plan view" })).toHaveTextContent("cannot create a WebGL context");
    expect(screen.getByText("Inspector stays")).toBeInTheDocument();
    // A loaded session model cannot render without 3D: the model workflow is told explicitly.
    expect(onImportedModelStatusChange).toHaveBeenCalledWith("error", expect.stringContaining("cannot be shown without the 3D view"));
    control.throwOnRender = null;
    await user.click(screen.getByRole("button", { name: "Retry 3D view" }));
    expect(await screen.findByTestId("scene")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "2D plan view" })).not.toBeInTheDocument();
  });

  it("describes a non-WebGL scene error without hiding the rest of the view", async () => {
    control.throwOnRender = new Error("bad geometry");
    render(<TwinViewport status={READY_STATUS} onRetry={vi.fn()} scene={sceneProps()} />);
    expect(await screen.findByText(/The 3D renderer stopped with an error \(bad geometry\)\./)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "2D plan legend" })).toHaveTextContent("active backend alert (larger square)");
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SpatialScenePanel } from "./SpatialScenePanel";
import { useSpatialScene } from "./spatialHooks";
import { getSpatialScene, putSpatialScene, getSpatialHistory, getSpatialRevision } from "./spatialApi";
import { EMPTY_SPATIAL_SCENE } from "./spatialScene";
import { ApiClientError } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { ModelRegistrationControls } from "./ModelRegistration";
import type { SpatialScene } from "@/shared/types/spatial";

vi.mock("./spatialApi", () => ({ getSpatialScene: vi.fn(), putSpatialScene: vi.fn(), getSpatialHistory: vi.fn(), getSpatialRevision: vi.fn() }));
const snapshot = { ...EMPTY_SPATIAL_SCENE, revision: 3 };
function Harness({ canWrite = true }: { canWrite?: boolean }) {
  const query = useSpatialScene("token", "network", true);
  return <SpatialScenePanel query={query} token="token" networkId="network" canWrite={canWrite} onSelectDevice={vi.fn()} />;
}
function mount(canWrite = true) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><Harness canWrite={canWrite} /></QueryClientProvider>);
}

describe("scene editing", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    useAuthStore.setState({ profile: operatorProfile, accessToken: "token", endingSession: false });
    useWorkspaceStore.setState({ networkId: "network" });
    vi.mocked(getSpatialScene).mockResolvedValue(snapshot);
    vi.mocked(putSpatialScene).mockResolvedValue({ ...snapshot, revision: 4 });
  });
  it("validates drafts and saves only after explicit confirmation using the loaded revision", async () => {
    mount(); await screen.findByText(/Server revision 3/);
    fireEvent.change(screen.getByLabelText("Spatial scene JSON"), { target: { value: "{" } });
    fireEvent.click(screen.getByText("Save scene replacement"));
    expect(putSpatialScene).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Spatial scene JSON"), { target: { value: JSON.stringify(EMPTY_SPATIAL_SCENE) } });
    expect(putSpatialScene).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Save scene replacement"));
    await screen.findByText("Saved revision 4.");
    expect(putSpatialScene).toHaveBeenCalledWith("token", "network", { expected_revision: 3, scene: EMPTY_SPATIAL_SCENE });
  });
  it("retains a retryable draft after authority contention, reloads the same revision and saves the exact replacement", async () => {
    vi.mocked(putSpatialScene).mockRejectedValueOnce(new ApiClientError("Organization authority is changing. Retry the operation.", "ORG_AUTHORITY_BUSY", 409));
    mount(); await screen.findByText(/Server revision 3/);
    const scene: SpatialScene = { ...EMPTY_SPATIAL_SCENE, objects: [{
      object_id: "survey-building", object_type: "building", parent_id: null, name: "Survey building", device_id: null,
      position: { x: 12, y: 0, z: 8 }, rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "operator-survey", accuracy_m: null },
    }] };
    const draft = JSON.stringify(scene, null, 4);
    fireEvent.change(screen.getByLabelText("Spatial scene JSON"), { target: { value: draft } });
    fireEvent.click(screen.getByText("Save scene replacement"));
    await screen.findByText("Organization authority is changing. Retry the operation.");
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(draft);
    expect(screen.getByText("Save scene replacement")).toBeEnabled();
    expect(putSpatialScene).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Reload server scene"));
    await screen.findByText("Server reloaded; unsaved draft retained for comparison.");
    expect(screen.getByText(/Server revision 3/)).toBeInTheDocument();
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(draft);
    expect(screen.queryByRole("button", { name: /Rebase draft/ })).not.toBeInTheDocument();
    expect(screen.getByText("Save scene replacement")).toBeEnabled();
    expect(putSpatialScene).toHaveBeenCalledTimes(1);
    vi.mocked(putSpatialScene).mockResolvedValueOnce({ ...scene, revision: 4 });
    fireEvent.click(screen.getByText("Save scene replacement"));
    await screen.findByText("Saved revision 4.");
    expect(putSpatialScene).toHaveBeenCalledTimes(2);
    for (const call of vi.mocked(putSpatialScene).mock.calls) expect(call).toEqual(["token", "network", { expected_revision: 3, scene }]);
    expect(window.confirm).toHaveBeenCalledTimes(2);
  });
  it("retains the exact draft on conflict/reload and requires explicit rebase before retry", async () => {
    vi.mocked(putSpatialScene).mockRejectedValueOnce(new ApiClientError("stale", "SPATIAL_REVISION_CONFLICT", 409));
    mount(); await screen.findByText(/Server revision 3/);
    const draft = JSON.stringify(EMPTY_SPATIAL_SCENE, null, 4);
    fireEvent.change(screen.getByLabelText("Spatial scene JSON"), { target: { value: draft } });
    fireEvent.click(screen.getByText("Save scene replacement"));
    await screen.findByRole("alert");
    expect(screen.getByText("Save scene replacement")).toBeDisabled();
    fireEvent.click(screen.getByText("Reload server scene"));
    await screen.findByText("Server reloaded; unsaved draft retained for comparison.");
    expect(screen.getByText("Save scene replacement")).toBeDisabled();
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(draft);
    expect(putSpatialScene).toHaveBeenCalledTimes(1);
    vi.mocked(getSpatialScene).mockResolvedValue({ ...snapshot, revision: 8 });
    fireEvent.click(screen.getByText("Reload server scene"));
    await screen.findByText(/Server revision 8/);
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(draft);
    expect(putSpatialScene).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Rebase draft to revision 8"));
    fireEvent.click(screen.getByText("Save scene replacement"));
    await waitFor(() => expect(putSpatialScene).toHaveBeenLastCalledWith("token", "network", { expected_revision: 8, scene: EMPTY_SPATIAL_SCENE }));
  });
  it("gates editing for readers and fails closed if write permission is revoked before save", async () => {
    const view = mount(false); await screen.findByText(/Server revision 3/);
    expect(screen.getByLabelText("Spatial scene JSON")).toBeDisabled();
    view.unmount(); mount(); await screen.findByText(/Server revision 3/);
    fireEvent.change(screen.getByLabelText("Spatial scene JSON"), { target: { value: JSON.stringify(EMPTY_SPATIAL_SCENE) } });
    act(() => {
      useAuthStore.setState({ profile: { ...operatorProfile, permissions: [] } });
      fireEvent.click(screen.getByText("Save scene replacement"));
    });
    await screen.findByText(/Current network and write:config permission required/);
    expect(putSpatialScene).not.toHaveBeenCalled();
  });
  it("imports validated JSON locally and preserves it after invalid imports and failed reloads", async () => {
    mount(); await screen.findByText(/Server revision 3/);
    const file = new File([""], "scene.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => JSON.stringify(EMPTY_SPATIAL_SCENE) });
    fireEvent.change(screen.getByLabelText("Import spatial scene JSON"), { target: { files: [file] } });
    await screen.findByText(/Imported and validated locally/);
    const draft = screen.getByLabelText<HTMLTextAreaElement>("Spatial scene JSON").value;
    const invalid = new File([""], "invalid.json");
    Object.defineProperty(invalid, "text", { value: async () => "{}" });
    fireEvent.change(screen.getByLabelText("Import spatial scene JSON"), { target: { files: [invalid] } });
    await screen.findByText("Expected a JSON object.");
    vi.mocked(getSpatialScene).mockRejectedValue(new ApiClientError("Denied", "FORBIDDEN", 403));
    fireEvent.click(screen.getByText("Reload server scene"));
    await screen.findByText(/Spatial scene unavailable: Denied/);
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(draft);
    expect(putSpatialScene).not.toHaveBeenCalled();
  });
  it("requires explicit valid local registration and labels it unsaved", () => {
    const apply = vi.fn(); render(<ModelRegistrationControls onApply={apply} />);
    expect(apply).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Scale X"), { target: { value: "0" } });
    expect(screen.getByText("Apply local registration")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Scale X"), { target: { value: "0.01" } });
    fireEvent.change(screen.getByLabelText("Registration source"), { target: { value: "survey" } });
    fireEvent.change(screen.getByLabelText("Position X"), { target: { value: "12" } });
    fireEvent.click(screen.getByText("Apply local registration"));
    expect(apply).toHaveBeenCalledWith({ version: 1, translation: { x: 12, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 }, scale: { x: 0.01, y: 1, z: 1 }, target_units: "m", target_up_axis: "y", source: "survey" });
    expect(screen.getByText("Registration applied locally — unsaved.")).toBeInTheDocument();
  });
  it("browses history and stages restore against current revision; racing PUT never rewrites history", async () => {
    vi.mocked(getSpatialHistory).mockResolvedValue({ items: [{ revision: 1, recorded_at: "2026-09-20T00:00:00Z", actor_id: null, origin: "baseline", object_count: 0 }], page: 1, page_size: 20, total: 21 });
    vi.mocked(getSpatialRevision).mockResolvedValue({ ...snapshot, revision: 1 });
    mount(); await screen.findByText(/Server revision 3/);
    fireEvent.click(screen.getByText("Browse spatial history"));
    fireEvent.click(await screen.findByText("Revision 1"));
    fireEvent.click(await screen.findByText("Stage revision 1 for restore"));
    expect(putSpatialScene).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(JSON.stringify(EMPTY_SPATIAL_SCENE, null, 2));
    vi.mocked(putSpatialScene).mockRejectedValueOnce(new ApiClientError("race", "SPATIAL_REVISION_CONFLICT", 409));
    fireEvent.click(screen.getByText("Save scene replacement"));
    await screen.findByRole("alert");
    expect(putSpatialScene).toHaveBeenCalledWith("token", "network", { expected_revision: 3, scene: EMPTY_SPATIAL_SCENE });
    expect(screen.getByText("Save scene replacement")).toBeDisabled();
    fireEvent.click(screen.getByText("Next history page"));
    await waitFor(() => expect(getSpatialHistory).toHaveBeenCalledWith("token", "network", 2, expect.any(AbortSignal)));
  });
});

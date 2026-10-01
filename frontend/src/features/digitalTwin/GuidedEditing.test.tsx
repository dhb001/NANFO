import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SpatialScenePanel } from "./SpatialScenePanel";
import { CustomGroupEditor } from "./CustomGroupEditor";
import { useSpatialScene } from "./spatialHooks";
import { getSpatialScene, putSpatialScene } from "./spatialApi";
import { listDevices, listDeviceGroups, upsertDeviceGroups } from "@/features/networks/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { ApiClientError } from "@/shared/lib/errors";
import type { SpatialObject, SpatialSceneSnapshot } from "@/shared/types/spatial";
import type { Device, DeviceGroupRecord } from "@/shared/types/network";
import type { ApiSuccess } from "@/shared/types/api";

vi.mock("./spatialApi", () => ({ getSpatialScene: vi.fn(), putSpatialScene: vi.fn() }));
vi.mock("@/features/networks/api", () => ({ listDevices: vi.fn(), listDeviceGroups: vi.fn(), upsertDeviceGroups: vi.fn() }));
const deviceId = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const object = (id: string, type: SpatialObject["object_type"], parent: string | null = null): SpatialObject => ({
  object_id: id, object_type: type, parent_id: parent, name: id, position: { x: 1, y: 2, z: 3 }, rotation: { x: 0, y: 0, z: 0 }, device_id: null,
  provenance: { source: "survey", accuracy_m: null },
});
const initial: SpatialSceneSnapshot = { version: 1, revision: 4, coordinate_system: { units: "m", up_axis: "y" }, objects: [object("building", "building"), object("floor", "floor", "building"), { ...object("wall", "wall", "floor"), geometry: null }] };
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const envelope = <T,>(data: T): ApiSuccess<T> => ({ success: true, data, errors: null, meta: { request_id: "test", timestamp: "2026-09-20T00:00:00Z" } });
function Harness() {
  const token = useAuthStore((state) => state.accessToken);
  const query = useSpatialScene(token, "network", true);
  return <SpatialScenePanel query={query} token={token} networkId="network" canWrite onSelectDevice={vi.fn()} />;
}
function mount(node = <Harness />) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{node}</QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  useAuthStore.setState({ profile: operatorProfile, accessToken: "token", endingSession: false });
  useWorkspaceStore.setState({ networkId: "network" });
  vi.mocked(getSpatialScene).mockResolvedValue(initial);
  vi.mocked(listDevices).mockImplementation(async (_token, _network, page = 1) => ({ data: {
    items: Array.from({ length: page === 1 ? 20 : 1 }, (_, i) => ({ device_id: deviceId((page - 1) * 20 + i + 1), hostname: `device-${(page - 1) * 20 + i + 1}`, device_type: "switch" } as Device)),
    page, page_size: 20, total: 21,
  } } as Awaited<ReturnType<typeof listDevices>>));
  vi.mocked(listDeviceGroups).mockResolvedValue(envelope({ items: [], total: 0 }));
  vi.mocked(upsertDeviceGroups).mockResolvedValue(envelope({ items: [], total: 0 }));
});

describe("guided spatial replacement", () => {
  it("validates dimensions/parents, retains unknowns and draft revision over rotation and conflict", async () => {
    mount(); await screen.findByText(/Server revision 4/);
    fireEvent.click(screen.getByText("Guided object editor"));
    change("Scene object", "floor"); change("Geometry", "slab");
    change("width", "12"); change("depth", "8"); change("thickness", "-1");
    expect(screen.getByText("Save scene replacement")).toBeDisabled();
    fireEvent.click(screen.getByText("Stage object in draft"));
    expect(screen.getByLabelText<HTMLTextAreaElement>("Spatial scene JSON").value).not.toContain('"slab"');
    change("thickness", "0.2"); change("Parent object", "wall");
    fireEvent.click(screen.getByText("Stage object in draft"));
    expect(screen.getByText("Invalid parent hierarchy or cycle.")).toBeInTheDocument();
    change("Parent object", "building");
    act(() => useAuthStore.setState({ accessToken: "rotated" }));
    await waitFor(() => expect(screen.getByText("Stage object in draft")).toBeEnabled());
    expect(screen.getByLabelText("thickness")).toHaveValue(0.2);
    fireEvent.click(screen.getByText("Stage object in draft"));
    const draft = screen.getByLabelText<HTMLTextAreaElement>("Spatial scene JSON").value;
    const scene = JSON.parse(draft);
    expect(scene.objects[0]).not.toHaveProperty("geometry");
    expect(scene.objects[1].geometry).toEqual({ kind: "slab", width: 12, depth: 8, thickness: 0.2 });
    expect(scene.objects[1].provenance.accuracy_m).toBeNull();
    expect(scene.objects[2].geometry).toBeNull();
    expect(putSpatialScene).not.toHaveBeenCalled();
    vi.mocked(putSpatialScene).mockRejectedValue(new ApiClientError("race", "SPATIAL_REVISION_CONFLICT", 409));
    fireEvent.click(screen.getByText("Save scene replacement"));
    await screen.findByRole("alert");
    expect(putSpatialScene).toHaveBeenCalledWith("rotated", "network", { expected_revision: 4, scene });
    vi.mocked(getSpatialScene).mockResolvedValue({ ...initial, revision: 7 });
    fireEvent.click(screen.getByText("Reload server scene"));
    await screen.findByText(/Server revision 7/);
    expect(screen.getByLabelText("Spatial scene JSON")).toHaveValue(draft);
    expect(screen.getByText("Save scene replacement")).toBeDisabled();
  });

  it("stages box/wall material without RF defaults and keeps JSON parity", async () => {
    mount(); await screen.findByText(/Server revision 4/);
    fireEvent.click(screen.getByText("Guided object editor"));
    change("Scene object", "building"); change("Geometry", "box");
    change("width", "20"); change("depth", "10"); change("height", "5");
    fireEvent.click(screen.getByText("Stage object in draft"));
    change("Scene object", "wall"); change("Geometry", "wall");
    change("length", "8"); change("height", "3"); change("thickness", "0.1");
    change("Material name", "survey material"); change("Material source", "site record");
    fireEvent.click(screen.getByText("Stage object in draft"));
    const scene = JSON.parse(screen.getByLabelText<HTMLTextAreaElement>("Spatial scene JSON").value);
    expect(scene.objects[0].geometry).toEqual({ kind: "box", width: 20, depth: 10, height: 5 });
    expect(scene.objects[2].geometry.material).toEqual({ name: "survey material", source: "site record", attenuation_db: null });
    fireEvent.click(screen.getByText("Validate JSON"));
    expect(screen.getByText(/Valid scene: 3 objects/)).toBeInTheDocument();
  });

  it("creates an inventory-associated object from the final page, with explicit transforms", async () => {
    mount(); await screen.findByText(/Server revision 4/);
    fireEvent.click(screen.getByText("Guided object editor"));
    change("Object ID", "device-object"); change("Object name", "Actual device"); change("Object type", "device");
    for (const key of ["position", "rotation"]) for (const axis of ["x", "y", "z"]) change(`${key} ${axis}`, "0");
    change("Provenance source", "operator placement");
    await screen.findByLabelText(/device-1 ·/);
    fireEvent.click(screen.getByText("Next inventory page"));
    fireEvent.click(await screen.findByLabelText(/device-21 ·/));
    fireEvent.click(screen.getByText("Stage object in draft"));
    expect(JSON.parse(screen.getByLabelText<HTMLTextAreaElement>("Spatial scene JSON").value).objects.at(-1)).toMatchObject({ object_id: "device-object", device_id: deviceId(21), provenance: { accuracy_m: null } });
    expect(putSpatialScene).not.toHaveBeenCalled();
  });
});

describe("custom group membership", () => {
  it("creates exact non-destructive payload from multiple inventory pages and confirms save", async () => {
    mount(<CustomGroupEditor token="token" networkId="network" canWrite />);
    change("Stable group key", "my-group"); change("Group name", "My group");
    fireEvent.click(await screen.findByLabelText(/device-1 ·/));
    fireEvent.click(screen.getByText("Next inventory page"));
    fireEvent.click(await screen.findByLabelText(/device-21 ·/));
    expect(listDevices).toHaveBeenCalledWith("token", "network", 2, 20, expect.any(AbortSignal));
    expect(upsertDeviceGroups).not.toHaveBeenCalled();
    vi.mocked(window.confirm).mockReturnValue(false);
    fireEvent.click(screen.getByText("Save custom group"));
    expect(upsertDeviceGroups).not.toHaveBeenCalled();
    vi.mocked(window.confirm).mockReturnValue(true);
    fireEvent.click(screen.getByText("Save custom group"));
    await screen.findByText("Custom group saved.");
    expect(upsertDeviceGroups).toHaveBeenCalledWith("token", "network", { replaceExisting: false, groups: [{ group_key: "my-group", name: "My group", group_type: "custom", description: null, selector: {}, device_ids: [deviceId(1), deviceId(21)] }] });
  });

  it("retains off-page members/selector/stable key while editing and retains failed drafts", async () => {
    const group = { group_key: "stable", name: "Original", group_type: "custom" as const, description: "Preserved", selector: { site_prefix: "site" }, device_ids: [deviceId(21)] };
    const record: DeviceGroupRecord = { ...group, device_group_id: "group", network_id: "network", created_at: "2026-09-20", updated_at: "2026-09-20" };
    vi.mocked(listDeviceGroups).mockResolvedValue(envelope({ items: [record], total: 1 }));
    vi.mocked(upsertDeviceGroups).mockRejectedValue(new Error("Denied"));
    mount(<CustomGroupEditor token="token" networkId="network" canWrite />);
    await screen.findByText("Original (stable)"); change("Edit custom group", "stable");
    expect(screen.getByLabelText("Stable group key")).toHaveAttribute("readonly");
    change("Group name", "Edited"); fireEvent.click(await screen.findByLabelText(/device-1 ·/));
    fireEvent.click(screen.getByText("Save custom group"));
    await screen.findByText(/Denied Draft retained/);
    // C8: edits of a loaded group are pinned to the updated_at they were read at.
    const pinned = { expected_updated_at: "2026-09-20" };
    expect(upsertDeviceGroups).toHaveBeenCalledWith("token", "network", { replaceExisting: false, groups: [{ ...group, name: "Edited", device_ids: [deviceId(21), deviceId(1)], ...pinned }] });
    fireEvent.click(screen.getByText(`Remove ${deviceId(21)}`));
    fireEvent.click(screen.getByText("Save custom group"));
    await waitFor(() => expect(upsertDeviceGroups).toHaveBeenLastCalledWith("token", "network", { replaceExisting: false, groups: [{ ...group, name: "Edited", device_ids: [deviceId(1)], ...pinned }] }));
    fireEvent.click(screen.getByText("Use explicit membership only"));
    fireEvent.click(screen.getByText("Save custom group"));
    await waitFor(() => expect(upsertDeviceGroups).toHaveBeenLastCalledWith("token", "network", { replaceExisting: false, groups: [{ ...group, name: "Edited", selector: {}, device_ids: [deviceId(1)], ...pinned }] }));
  });

  it("reports DEVICE_GROUP_CONFLICT, keeps the draft and re-pins to the saved revision", async () => {
    const group = { group_key: "stable", name: "Original", group_type: "custom" as const, description: null, selector: {}, device_ids: [deviceId(21)] };
    const record: DeviceGroupRecord = { ...group, device_group_id: "group", network_id: "network", created_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z" };
    vi.mocked(listDeviceGroups).mockResolvedValue(envelope({ items: [record], total: 1 }));
    vi.mocked(upsertDeviceGroups)
      .mockRejectedValueOnce(new ApiClientError("changed", "DEVICE_GROUP_CONFLICT", 409))
      .mockResolvedValueOnce(envelope({ items: [{ ...record, name: "Edited", updated_at: "2026-09-21T00:00:00Z" }], total: 1 }))
      .mockResolvedValueOnce(envelope({ items: [{ ...record, name: "Edited again", updated_at: "2026-09-22T00:00:00Z" }], total: 1 }));
    mount(<CustomGroupEditor token="token" networkId="network" canWrite />);
    await screen.findByText("Original (stable)"); change("Edit custom group", "stable");
    change("Group name", "Edited");
    fireEvent.click(screen.getByText("Save custom group"));
    expect(await screen.findByText(/DEVICE_GROUP_CONFLICT\). Nothing was changed/)).toHaveTextContent("Draft retained.");
    expect(screen.getByLabelText("Group name")).toHaveValue("Edited");
    fireEvent.click(screen.getByText("Save custom group"));
    await screen.findByText("Custom group saved.");
    change("Group name", "Edited again");
    fireEvent.click(screen.getByText("Save custom group"));
    await waitFor(() => expect(upsertDeviceGroups).toHaveBeenCalledTimes(3));
    expect(vi.mocked(upsertDeviceGroups).mock.calls.map((call) => call[2].groups[0].expected_updated_at))
      .toEqual(["2026-09-20T00:00:00Z", "2026-09-20T00:00:00Z", "2026-09-21T00:00:00Z"]);
  });
});

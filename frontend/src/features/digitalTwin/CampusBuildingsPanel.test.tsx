import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CampusBuildingRecord } from "@/shared/types/network";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useUiStore } from "@/shared/state/ui-store";
import { operatorProfile } from "@/test/profile";
import { CampusBuildingsPanel } from "./CampusBuildingsPanel";
import { useCampusBuildingsWorkflow } from "./useCampusBuildingsWorkflow";

const hooks = vi.hoisted(() => ({ buildings: vi.fn(), upsert: vi.fn() }));

vi.mock("@/features/networks/hooks", () => ({
  useCampusBuildings: () => hooks.buildings(),
  useUpsertCampusBuildings: () => ({ mutateAsync: hooks.upsert, isPending: false }),
}));

type Ring = Array<[number, number]>;
const rect = (lon: number, lat: number): Ring => [[lon, lat], [lon + 0.0004, lat], [lon + 0.0004, lat + 0.0003], [lon, lat + 0.0003], [lon, lat]];
const geojson = (...names: string[]) => new File([JSON.stringify({
  type: "FeatureCollection",
  features: names.map((name, index) => ({ type: "Feature", properties: { building: "yes", name, campus: "strathmore", "building:levels": "2" }, geometry: { type: "Polygon", coordinates: [rect(36.8 + index * 0.001, -1.3)] } })),
})], "campus.geojson", { type: "application/geo+json" });

function record(id: string, label: string, overrides: Partial<CampusBuildingRecord> = {}): CampusBuildingRecord {
  return {
    campus_building_id: `row-${id}`, network_id: "n", building_id: id, campus_key: "strathmore", building_key: id.split(":")[1] ?? id, label,
    geometry: "box", x: 0, z: 0, base_y: 0, width: 10, depth: 10, height: 6, floors: 2, footprint: [], wall_material: null, attenuation_db: null,
    source: "osm", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z", ...overrides,
  };
}

function query(items: CampusBuildingRecord[] | null, options: { isError?: boolean; total?: number; refetch?: ReturnType<typeof vi.fn> } = {}) {
  const data = items ? { items, total: options.total ?? items.length } : undefined;
  return { data, isLoading: false, isError: options.isError ?? false, error: options.isError ? new Error("buildings down") : null,
    refetch: options.refetch ?? vi.fn().mockResolvedValue({ data, isError: false }) };
}

function Harness() {
  const campus = useCampusBuildingsWorkflow(true);
  return <CampusBuildingsPanel campus={campus} />;
}

async function importBuildings(user: ReturnType<typeof userEvent.setup>, ...names: string[]) {
  await user.upload(screen.getByLabelText("Campus GeoJSON file"), geojson(...names));
  expect(await screen.findByText(`buildings ${names.length}`)).toBeInTheDocument();
}

describe("CampusBuildingsPanel", () => {
  beforeEach(() => {
    hooks.buildings.mockReset();
    hooks.upsert.mockReset().mockResolvedValue({ items: [], total: 0 });
    useAuthStore.setState({ profile: operatorProfile, accessToken: "token-1" });
    useWorkspaceStore.setState({ networkId: "00000000-0000-0000-0000-000000000333" });
    useUiStore.setState({ toasts: [] });
  });

  it("writes directly when nothing is persisted yet", async () => {
    const user = userEvent.setup();
    hooks.buildings.mockReturnValue(query([]));
    render(<Harness />);
    await importBuildings(user, "Engineering Block");
    await user.click(screen.getByRole("button", { name: "Persist Buildings to Network" }));
    await waitFor(() => expect(hooks.upsert).toHaveBeenCalledTimes(1));
    expect(hooks.upsert.mock.calls[0]?.[0]).toMatchObject({ replaceExisting: true, buildings: [expect.objectContaining({ building_id: "strathmore:engineering-block", floors: 2 })] });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requires a reviewed diff against a fresh read before replacing persisted buildings", async () => {
    const user = userEvent.setup();
    const stale = [record("strathmore:engineering-block", "Engineering Block")];
    const fresh = [record("strathmore:engineering-block", "Engineering Block", { floors: 5 }), record("strathmore:old-hall", "Old Hall")];
    const refetch = vi.fn().mockResolvedValue({ data: { items: fresh, total: 2 }, isError: false });
    hooks.buildings.mockReturnValue(query(stale, { refetch }));
    render(<Harness />);
    await importBuildings(user, "Engineering Block", "Library");
    const trigger = screen.getByRole("button", { name: "Persist Buildings to Network" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: "Review campus building changes" });
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(hooks.upsert).not.toHaveBeenCalled();
    // Diff comes from the fresh server list, not the cached one.
    expect(dialog).toHaveTextContent("1 added · 1 changed · 0 unchanged · 1 persisted buildings not in this import.");
    expect(within(dialog).getByRole("list", { name: "Changed" })).toHaveTextContent(/^Engineering Block \(strathmore:engineering-block\): .*floors/);
    expect(within(dialog).getByRole("list", { name: "Removed by replacement" })).toHaveTextContent("Old Hall (strathmore:old-hall)");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(hooks.upsert).not.toHaveBeenCalled();

    await user.click(trigger);
    const again = await screen.findByRole("dialog");
    await user.click(within(again).getByRole("radio", { name: /Add and update only/ }));
    expect(within(again).getByRole("list", { name: "Kept (not in this import)" })).toHaveTextContent("Old Hall");
    await user.click(within(again).getByRole("button", { name: "Add and update only" }));
    await waitFor(() => expect(hooks.upsert).toHaveBeenCalledTimes(1));
    expect(hooks.upsert.mock.calls[0]?.[0]).toMatchObject({ replaceExisting: false });
    expect(hooks.upsert.mock.calls[0]?.[0].buildings.map((item: { building_id: string }) => item.building_id)).toEqual(["strathmore:engineering-block", "strathmore:library"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("confirms a full replacement explicitly and keeps the dialog open with the error on failure", async () => {
    const user = userEvent.setup();
    hooks.buildings.mockReturnValue(query([record("strathmore:old-hall", "Old Hall")]));
    hooks.upsert.mockRejectedValueOnce(new Error("Request body too large")).mockResolvedValueOnce({ items: [], total: 1 });
    render(<Harness />);
    await importBuildings(user, "Library");
    await user.click(screen.getByRole("button", { name: "Persist Buildings to Network" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Replace persisted buildings" });
    expect(confirm).toHaveClass("button--danger");
    await user.click(confirm);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Request body too large Reload persisted buildings to check the outcome before retrying.");
    expect(hooks.upsert.mock.calls[0]?.[0]).toMatchObject({ replaceExisting: true });
    await user.click(within(dialog).getByRole("button", { name: "Replace persisted buildings" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ title: "Campus buildings persisted" });
  });

  it("offers only add-and-update when the server list is incomplete", async () => {
    const user = userEvent.setup();
    hooks.buildings.mockReturnValue(query([record("strathmore:old-hall", "Old Hall")], { total: 7 }));
    render(<Harness />);
    await importBuildings(user, "Library");
    await user.click(screen.getByRole("button", { name: "Persist Buildings to Network" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("fewer buildings than it holds");
    expect(within(dialog).getByRole("radio", { name: /Replace all persisted buildings/ })).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: /Add and update only/ })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: "Add and update only" })).toBeEnabled();
  });

  it("traps Tab inside the review dialog, including its disclosure summaries", async () => {
    const user = userEvent.setup();
    hooks.buildings.mockReturnValue(query([record("strathmore:old-hall", "Old Hall")]));
    render(<Harness />);
    await importBuildings(user, "Library");
    await user.click(screen.getByRole("button", { name: "Persist Buildings to Network" }));
    const dialog = await screen.findByRole("dialog");
    const first = within(dialog).getByText("Added (1)");
    const last = within(dialog).getByRole("button", { name: "Replace persisted buildings" });
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("shows explicit error and retry states instead of a zero count and blocks persisting", async () => {
    const user = userEvent.setup();
    const retry = vi.fn().mockResolvedValue({ data: undefined, isError: true });
    hooks.buildings.mockReturnValue(query(null, { isError: true, refetch: retry }));
    render(<Harness />);
    const region = screen.getByRole("region", { name: "Campus buildings" });
    expect(within(region).getByRole("alert")).toHaveTextContent("Persisted campus buildings unavailable: buildings down");
    expect(within(region).queryByText(/persisted \d/)).not.toBeInTheDocument();
    await importBuildings(user, "Library");
    expect(screen.getByRole("button", { name: "Persist Buildings to Network" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry loading buildings" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("does not open a review when the fresh read fails", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn().mockResolvedValue({ data: undefined, isError: true });
    hooks.buildings.mockReturnValue(query([record("strathmore:old-hall", "Old Hall")], { refetch }));
    render(<Harness />);
    await importBuildings(user, "Library");
    await user.click(screen.getByRole("button", { name: "Persist Buildings to Network" }));
    expect(await screen.findByText(/Could not reload the persisted buildings to compare against/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(hooks.upsert).not.toHaveBeenCalled();
  });
});

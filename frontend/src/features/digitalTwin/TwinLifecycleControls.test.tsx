import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TwinLifecycleControls } from "./TwinLifecycleControls";
import { CustomGroupEditor } from "./CustomGroupEditor";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import type { CampusModelAssetRecord, DeviceGroupRecord } from "@/shared/types/network";

const asset = { campus_model_asset_id: "asset-old", network_id: "network", model_file_name: "old.gltf" } as CampusModelAssetRecord;
const retired = vi.fn();
const reload = vi.fn().mockResolvedValue(true);
const envelope = (data: unknown) => Response.json({ success: true, data, meta: {}, errors: null });
function Harness() {
  const [id, setId] = useState(asset.campus_model_asset_id);
  return <TwinLifecycleControls networkId="network" assets={[asset]} selectedId={id} onSelect={setId} onReload={reload} onRetired={(value) => { retired(value); setId(""); }} />;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  useAuthStore.setState({ profile: operatorProfile, accessToken: "token", endingSession: false, userId: "user" });
  useWorkspaceStore.setState({ networkId: "network", workspaceId: "workspace", organizationId: "org" });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("retires exactly the confirmed asset with an empty DELETE, clears selection only after 204", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock); render(<Harness />);
  vi.mocked(window.confirm).mockReturnValueOnce(false);
  fireEvent.click(screen.getByText("Retire selected asset"));
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Retire selected asset"));
  await screen.findByText("Selected asset retired.");
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/networks/network/campus/model-assets/asset-old"), expect.objectContaining({ method: "DELETE", body: undefined, headers: { Authorization: "Bearer token" } }));
  expect(retired).toHaveBeenCalledWith("asset-old");
  expect(screen.getByLabelText("Persisted model asset")).toHaveValue("");
  expect(reload).toHaveBeenCalledOnce();
});

it("retains selected asset on denial and refuses changed authority/scope after confirmation", async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ success: false, errors: { code: "FORBIDDEN", message: "Denied" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetchMock); render(<Harness />);
  fireEvent.click(screen.getByText("Retire selected asset"));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Persisted model asset")).toHaveValue("asset-old");
  expect(retired).not.toHaveBeenCalled();
  vi.mocked(window.confirm).mockImplementationOnce(() => { useWorkspaceStore.setState({ networkId: "foreign" }); return true; });
  fireEvent.click(screen.getByText("Retire selected asset"));
  await screen.findByText(/Session context changed/);
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("clears whole groups/buildings only explicitly, using exact empty replacement payloads", async () => {
  const fetchMock = vi.fn().mockResolvedValue(envelope({ items: [], total: 0 }));
  vi.stubGlobal("fetch", fetchMock); render(<Harness />);
  vi.mocked(window.confirm).mockReturnValueOnce(false);
  fireEvent.click(screen.getByText("Clear all persisted groups"));
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Clear all persisted groups"));
  await screen.findByText("All active groups cleared.");
  expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/networks/network/device-groups"), expect.objectContaining({ method: "POST", body: JSON.stringify({ replace_existing: true, groups: [] }) }));
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("including unrelated groups"));
  fetchMock.mockResolvedValueOnce(envelope({ items: [], total: 0 }));
  fireEvent.click(screen.getByText("Clear all persisted buildings"));
  await screen.findByText("All active buildings cleared.");
  expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/networks/network/campus/buildings"), expect.objectContaining({ method: "POST", body: JSON.stringify({ buildings: [], replace_existing: true }) }));
  expect(retired).not.toHaveBeenCalled();
});

it("denies readers and reports failed clearing without claiming success", async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ success: false, errors: { code: "FORBIDDEN", message: "Clear denied" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetchMock);
  useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:topology"] } });
  render(<Harness />);
  expect(screen.getByText("Clear all persisted buildings")).toBeDisabled();
  expect(screen.getByText("Retire selected asset")).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
  act(() => useAuthStore.setState({ profile: operatorProfile, accessToken: "rotated" }));
  fireEvent.click(screen.getByText("Clear all persisted buildings"));
  await screen.findByText(/Clear denied/);
  expect(fetchMock).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer rotated" }) }));
  expect(reload).not.toHaveBeenCalled();
  expect(retired).not.toHaveBeenCalled();
});

it("removes a noncustom final-member group by fresh reviewed replacement retaining all other definitions", async () => {
  const base = { device_group_id: "id", network_id: "network", created_at: "date", updated_at: "date", description: null, selector: {}, device_ids: ["device"] };
  const target: DeviceGroupRecord = { ...base, group_key: "target", name: "Target", group_type: "functional" };
  const other: DeviceGroupRecord = { ...base, group_key: "other", name: "Other", group_type: "custom", selector: { site_prefix: "campus" } };
  const posts: unknown[] = [];
  const fetchMock = vi.fn(async (url: string, options: RequestInit) => {
    if (options.method === "POST") { posts.push(JSON.parse(String(options.body))); return envelope({ items: [other], total: 1 }); }
    return envelope(url.includes("device-groups") ? { items: [target, other], total: 2 } : { items: [], page: 1, page_size: 20, total: 0 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CustomGroupEditor token="token" networkId="network" canWrite /></QueryClientProvider>);
  await screen.findByText("Target (target)");
  fireEvent.change(screen.getByLabelText("Edit custom group"), { target: { value: "target" } });
  fireEvent.click(screen.getByText("Remove device"));
  expect(posts).toHaveLength(0);
  fireEvent.click(screen.getByText("Save custom group"));
  await screen.findByText(/An empty group cannot be saved/);
  fireEvent.click(screen.getByText("Remove selected persisted group"));
  await screen.findByText("Selected group removed; other groups retained.");
  expect(posts).toEqual([{ replace_existing: true, groups: [{ group_key: "other", name: "Other", group_type: "custom", description: null, selector: { site_prefix: "campus" }, device_ids: ["device"] }] }]);
  expect(window.confirm).toHaveBeenLastCalledWith(expect.stringContaining("retains 1 groups: other"));
});

it("does not apply a late retirement result to a changed network", async () => {
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
  render(<Harness />);
  fireEvent.click(screen.getByText("Retire selected asset"));
  act(() => useWorkspaceStore.setState({ networkId: "other" }));
  resolve(new Response(null, { status: 204 }));
  await waitFor(() => expect(retired).not.toHaveBeenCalled());
  await screen.findByRole("alert");
});

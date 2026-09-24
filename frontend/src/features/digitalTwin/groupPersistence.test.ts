import { afterEach, expect, it, vi } from "vitest";
import { upsertDeviceGroups } from "@/features/networks/api";

afterEach(() => vi.unstubAllGlobals());

it("sends a non-destructive upsert request retaining unrelated groups", async () => {
  const unrelated = { group_key: "unrelated-ops", name: "Unrelated", group_type: "custom" };
  let stored = [unrelated];
  const fetchMock = vi.fn<typeof fetch>(async (_url, options) => {
    const request = JSON.parse(String(options?.body)) as { replace_existing: boolean; groups: typeof stored };
    expect(request.replace_existing).toBe(false);
    stored = [...(request.replace_existing ? [] : stored), ...request.groups];
    return Response.json({ success: true, data: { items: stored, total: stored.length }, meta: {}, errors: null });
  });
  vi.stubGlobal("fetch", fetchMock);
  const response = await upsertDeviceGroups("token", "network", { groups: [{ group_key: "wireless-campus", name: "Campus wireless", group_type: "functional", device_ids: ["d"] }] });
  expect(response.data.items).toContainEqual(unrelated);
  expect(response.data.total).toBe(2);
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/networks/network/device-groups"), expect.objectContaining({ method: "POST" }));
});

it("sends the custom editor's exact stable-key membership payload", async () => {
  const group = { group_key: "operator-group", name: "Operator group", group_type: "custom" as const, description: null, selector: {}, device_ids: ["00000000-0000-0000-0000-000000000021"] };
  const fetchMock = vi.fn<typeof fetch>(async (_url, options) => {
    expect(JSON.parse(String(options?.body))).toEqual({ replace_existing: false, groups: [group] });
    return Response.json({ success: true, data: { items: [], total: 0 }, meta: {}, errors: null });
  });
  vi.stubGlobal("fetch", fetchMock);
  await upsertDeviceGroups("token", "network", { replaceExisting: false, groups: [group] });
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("forwards C8 expected_updated_at per group only when present", async () => {
  const fetchMock = vi.fn<typeof fetch>(async () => Response.json({ success: true, data: { items: [], total: 0 }, meta: {}, errors: null }));
  vi.stubGlobal("fetch", fetchMock);
  await upsertDeviceGroups("token", "network", { replaceExisting: false, groups: [
    { group_key: "pinned", name: "Pinned", group_type: "functional", selector: { functional_group: "wireless" }, device_ids: [], expected_updated_at: "2026-09-24T10:00:00.123456Z" },
    { group_key: "new", name: "New", group_type: "operational", selector: { site_prefix: "campus-a" }, device_ids: [] },
  ] });
  const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body)) as { groups: Array<Record<string, unknown>> };
  expect(body.groups[0].expected_updated_at).toBe("2026-09-24T10:00:00.123456Z");
  expect(body.groups[1]).not.toHaveProperty("expected_updated_at");
});

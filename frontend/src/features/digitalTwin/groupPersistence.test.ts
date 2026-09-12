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

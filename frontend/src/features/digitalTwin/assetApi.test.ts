import { afterEach, expect, it, vi } from "vitest";
import { listCampusModelAssets, upsertCampusModelAssets } from "@/features/networks/api";

afterEach(() => vi.unstubAllGlobals());
it("requests only bounded metadata pages and forwards cancellation", async () => {
  const data = { items: [{ campus_model_asset_id: "asset" }], total: 41, page: 3, page_size: 20 };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true, data, meta: {}, errors: null })));
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  expect((await listCampusModelAssets("test-token", "n", 3, 20, controller.signal)).data).toEqual(data);
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/campus/model-assets?include_data=false&page=3&page_size=20"), expect.objectContaining({ signal: controller.signal }));
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("preserves registration omission vs explicit clearing in the existing asset POST", async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ success: true, data: { items: [], total: 0 }, meta: {}, errors: null })));
  vi.stubGlobal("fetch", fetch);
  const input = { model_file_name: "a.glb", model_mime_type: "model/gltf-binary", model_data_base64: "AA==", model_sha256: "a".repeat(64), model_size_bytes: 1, mapping_by_device_id: {} };
  await upsertCampusModelAssets("test-token", "n", input);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).not.toHaveProperty("registration");
  await upsertCampusModelAssets("test-token", "n", { ...input, registration: null });
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toHaveProperty("registration", null);
});

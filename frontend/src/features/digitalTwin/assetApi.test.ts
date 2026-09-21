import { afterEach, expect, it, vi } from "vitest";
import { upsertCampusModelAssets } from "@/features/networks/api";

afterEach(() => vi.unstubAllGlobals());
it("preserves registration omission vs explicit clearing in the existing asset POST", async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ success: true, data: { items: [], total: 0 }, meta: {}, errors: null })));
  vi.stubGlobal("fetch", fetch);
  const input = { model_file_name: "a.glb", model_mime_type: "model/gltf-binary", model_data_base64: "AA==", model_sha256: "a".repeat(64), model_size_bytes: 1, mapping_by_device_id: {} };
  await upsertCampusModelAssets("test-token", "n", input);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).not.toHaveProperty("registration");
  await upsertCampusModelAssets("test-token", "n", { ...input, registration: null });
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toHaveProperty("registration", null);
});

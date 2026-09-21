import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadModelBytes } from "./assetDownload";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import type { CampusModelAssetRecord } from "@/shared/types/network";

const asset = { network_id: "n", campus_model_asset_id: "a", model_size_bytes: 3, model_sha256: "a".repeat(64), model_mime_type: "model/gltf-binary", download_path: "https://untrusted.invalid/" } as CampusModelAssetRecord;
describe("protected model binary download", () => {
  beforeEach(() => { useAuthStore.setState({ accessToken: "token", endingSession: false }); useWorkspaceStore.setState({ networkId: "n" }); });
  afterEach(() => vi.unstubAllGlobals());
  const response = (bytes = [1, 2, 3]) => new Response(new Uint8Array(bytes), { headers: { "Content-Type": "model/gltf-binary", "ETag": `"${asset.model_sha256}"` } });
  it("uses authorized identity URL, bounds bytes, ignores server path", async () => {
    const fetch = vi.fn().mockResolvedValue(response()); vi.stubGlobal("fetch", fetch);
    expect(await downloadModelBytes(asset)).toEqual(new Uint8Array([1, 2, 3]));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/networks/n/campus-model-assets/a/download"), expect.objectContaining({ headers: { Authorization: "Bearer token" }, redirect: "error", cache: "no-store" }));
  });
  it("rejects size/header mismatch, canonical denial and context changes", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response([1, 2, 3, 4])).mockResolvedValueOnce(new Response("", { headers: { "Content-Type": "text/html" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: false, errors: { code: "FORBIDDEN", message: "Denied" } }), { status: 403 }));
    vi.stubGlobal("fetch", fetch);
    await expect(downloadModelBytes(asset)).rejects.toThrow("length mismatch");
    await expect(downloadModelBytes(asset)).rejects.toThrow("headers changed");
    await expect(downloadModelBytes(asset)).rejects.toMatchObject({ status: 403 });
    fetch.mockImplementation(async () => { useWorkspaceStore.setState({ networkId: "other" }); return response(); });
    await expect(downloadModelBytes(asset)).rejects.toThrow("context changed");
  });
});

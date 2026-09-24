import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadModelBytes } from "./assetDownload";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import type { CampusModelAssetRecord } from "@/shared/types/network";
import { webcrypto } from "node:crypto";
import fixture from "@/test/fixtures/asset-download.json";
import { decodePersistedModel, MAX_MODEL_BYTES } from "./modelAsset";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("@/features/auth/session", () => ({ refreshSession: refresh }));

const asset = { network_id: "n", campus_model_asset_id: "a", model_size_bytes: 3, model_sha256: "a".repeat(64), model_mime_type: "model/gltf-binary", download_path: "https://untrusted.invalid/" } as CampusModelAssetRecord;
describe("protected model binary download", () => {
  beforeEach(() => { useAuthStore.setState({ accessToken: "token", endingSession: false }); useWorkspaceStore.setState({ networkId: "n" }); });
  afterEach(() => vi.unstubAllGlobals());
  const response = (bytes = [1, 2, 3]) => new Response(new Uint8Array(bytes), { headers: { "Content-Type": "application/octet-stream", "ETag": `"sha256:${asset.model_sha256}"` } });
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
  it("consumes the actual backend-header fixture and verifies SHA, size and local MIME", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const metadata = { ...asset, model_file_name: "campus.gltf", model_mime_type: "model/gltf+json", model_size_bytes: 51, model_sha256: fixture.sha256, mapping_by_device_id: {} };
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(fixture.body, { headers: fixture.headers })));
    vi.stubGlobal("fetch", fetch);
    const bytes = await downloadModelBytes(metadata);
    expect((await decodePersistedModel(metadata, "n", new Set(), bytes)).size).toBe(51);
    fetch.mockImplementation(() => Promise.resolve(new Response(fixture.body.replace("2.0", "2.1"), { headers: fixture.headers })));
    await expect(decodePersistedModel(metadata, "n", new Set(), await downloadModelBytes(metadata))).rejects.toThrow("SHA-256");
    fetch.mockImplementation(() => Promise.resolve(new Response(fixture.body.slice(1), { headers: fixture.headers })));
    await expect(downloadModelBytes(metadata)).rejects.toThrow("length mismatch");
    await expect(decodePersistedModel({ ...metadata, model_mime_type: "text/html" }, "n", new Set(), bytes)).rejects.toThrow("MIME");
  });
  it.each<Record<string, string>>([{ "Content-Type": "model/gltf-binary" }, { "Content-Type": "text/html" }, { ETag: `"sha256:${"b".repeat(64)}"` }, { ETag: `W/"sha256:${"b".repeat(64)}"` }, { ETag: `"${"b".repeat(64)}"` }, { "Content-Length": "4" }])("rejects non-contract headers %j", async (headers) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "application/octet-stream", ETag: `"sha256:${asset.model_sha256}"`, ...headers } })));
    await expect(downloadModelBytes(asset)).rejects.toThrow("headers changed");
  });
  it.each<Record<string, string>>([{ ETag: `W/"sha256:${"a".repeat(64)}"` }, { ETag: `"sha256:${"A".repeat(64)}"` }, { ETag: `"${"a".repeat(64)}"` }, { ETag: 'W/"5f3-opaque-proxy"' }, {}, { "Content-Type": "Application/Octet-Stream; charset=binary" }])("accepts weak, legacy, opaque or absent validators (SHA-256 is authoritative) %j", async (headers) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "application/octet-stream", ...headers } })));
    await expect(downloadModelBytes(asset)).resolves.toEqual(new Uint8Array([1, 2, 3]));
  });
  it("never sends If-None-Match and reports an intermediary 304 explicitly", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 304, headers: { ETag: `"sha256:${asset.model_sha256}"` } }));
    vi.stubGlobal("fetch", fetch);
    await expect(downloadModelBytes(asset)).rejects.toMatchObject({ status: 304, code: "ASSET_NOT_MODIFIED" });
    expect(fetch.mock.calls[0][1].headers).not.toHaveProperty("If-None-Match");
  });
  it("still fails closed on a body whose digest does not match metadata even with a matching weak ETag", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const metadata = { ...asset, model_file_name: "campus.gltf", model_mime_type: "model/gltf+json", model_size_bytes: 51, model_sha256: fixture.sha256, mapping_by_device_id: {} };
    const tampered = fixture.body.replace("2.0", "2.1");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(tampered, { headers: { ...fixture.headers, etag: `W/"sha256:${fixture.sha256}"` } })));
    await expect(decodePersistedModel(metadata, "n", new Set(), await downloadModelBytes(metadata))).rejects.toThrow("SHA-256");
  });
  it("uses the single model size limit", async () => {
    await expect(downloadModelBytes({ ...asset, model_size_bytes: MAX_MODEL_BYTES + 1 })).rejects.toThrow("Invalid asset size.");
  });
  it("retries once with a rotated token and rejects a session change during refresh", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(null, { status: 401 })).mockResolvedValueOnce(response());
    vi.stubGlobal("fetch", fetch);
    refresh.mockImplementation(async () => { useAuthStore.setState({ accessToken: "rotated" }); return true; });
    await expect(downloadModelBytes(asset)).resolves.toEqual(new Uint8Array([1, 2, 3]));
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe("Bearer rotated");
    fetch.mockResolvedValueOnce(new Response(null, { status: 401 }));
    refresh.mockImplementation(async () => { useAuthStore.setState({ generation: useAuthStore.getState().generation + 1 }); return true; });
    await expect(downloadModelBytes(asset)).rejects.toThrow("context changed");
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});

import { webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { decodePersistedModel, MAX_MODEL_BYTES, validateModelBytes } from "./modelAsset";
import type { CampusModelAssetRecord } from "@/shared/types/network";

function glb(document = { asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ name: "campus" }] }) {
  const json = JSON.stringify(document);
  const data = new TextEncoder().encode(json.padEnd(Math.ceil(json.length / 4) * 4, " "));
  const buffer = new ArrayBuffer(20 + data.length);
  const view = new DataView(buffer);
  [0x46546c67, 2, buffer.byteLength, data.length, 0x4e4f534a].forEach((value, index) => view.setUint32(index * 4, value, true));
  new Uint8Array(buffer, 20).set(data);
  return buffer;
}

async function asset(): Promise<CampusModelAssetRecord> {
  const bytes = glb();
  const digest = await webcrypto.subtle.digest("SHA-256", bytes);
  return { campus_model_asset_id: "a", network_id: "n", model_file_name: "campus.glb", model_mime_type: "model/gltf-binary",
    model_data_base64: btoa(String.fromCharCode(...new Uint8Array(bytes))), model_size_bytes: bytes.byteLength,
    model_sha256: Buffer.from(digest).toString("hex"), mapping_by_device_id: { d: "campus/building/f1" }, source: null, created_at: "", updated_at: "" };
}

describe("persisted model validation", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("decodes and parses a real GLB with scoped local mapping", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const record = await asset();
    const file = await decodePersistedModel(record, "n", new Set(["d"]));
    expect(file.name).toBe("campus.glb");
    expect(file.size).toBe(record.model_size_bytes);
  });
  it("fails closed on hash, base64, bounds, MIME, mapping, and network mismatch", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const record = await asset();
    for (const change of [
      { model_sha256: "0".repeat(64) }, { model_size_bytes: MAX_MODEL_BYTES + 1 },
      { model_size_bytes: record.model_size_bytes - 1 }, { model_data_base64: "!".repeat(record.model_data_base64.length) },
      { model_mime_type: "text/html" }, { mapping_by_device_id: { foreign: "campus" } }, { network_id: "foreign" },
    ]) await expect(decodePersistedModel({ ...record, ...change }, "n", new Set(["d"]))).rejects.toThrow();
  });
  it("rejects unsupported or malformed glTF and prevents external resource fetch", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    for (const document of [
      { asset: { version: "1.0" } },
      { asset: { version: "2.0" }, buffers: [{ uri: "https://example.org/secret.bin", byteLength: 1 }] },
      { asset: { version: "2.0" }, extensionsRequired: ["KHR_draco_mesh_compression"] },
    ]) await expect(validateModelBytes(new TextEncoder().encode(JSON.stringify(document)).buffer, "campus.gltf", "model/gltf+json")).rejects.toThrow();
    await expect(validateModelBytes(new TextEncoder().encode("not-a-glb").buffer, "campus.glb", "model/gltf-binary")).rejects.toThrow();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
  it("accepts self-contained supported glTF JSON", async () => {
    await expect(validateModelBytes(new TextEncoder().encode('{"asset":{"version":"2.0"},"scenes":[{}],"scene":0}').buffer, "campus.gltf", "model/gltf+json")).resolves.toBeUndefined();
  });
});

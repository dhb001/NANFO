import { webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bytesToBase64, decodePersistedModel, encodeBase64, loadValidatedModel, MAX_MODEL_BYTES, MAX_MODEL_SIZE_TEXT, sha256Hex, validateModelBytes } from "./modelAsset";

const loader = vi.hoisted(() => ({ constructed: 0 }));
vi.mock("three/examples/jsm/loaders/GLTFLoader.js", () => ({ GLTFLoader: class { constructor() { loader.constructed += 1; } } }));
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
      { model_size_bytes: record.model_size_bytes - 1 }, { model_data_base64: "!".repeat(record.model_data_base64!.length) },
      { model_mime_type: "text/html" }, { mapping_by_device_id: { foreign: "campus" } }, { network_id: "foreign" },
    ]) await expect(decodePersistedModel({ ...record, ...change }, "n", new Set(["d"]))).rejects.toThrow();
  });
  it("validates downloaded binary against metadata rather than falling back to valid inline bytes", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const record = await asset();
    expect((await decodePersistedModel(record, "n", new Set(["d"]), new Uint8Array(glb()))).size).toBe(record.model_size_bytes);
    const corrupt = new Uint8Array(glb()); corrupt[corrupt.length - 1] ^= 1;
    await expect(decodePersistedModel(record, "n", new Set(["d"]), corrupt)).rejects.toThrow("SHA-256");
    await expect(decodePersistedModel(record, "n", new Set(["d"]), corrupt.slice(1))).rejects.toThrow("size mismatch");
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
  it("validates structure with one JSON parse and never runs a second full glTF parse", async () => {
    const parse = vi.spyOn(JSON, "parse");
    await validateModelBytes(glb(), "campus.glb", "model/gltf-binary");
    expect(parse).toHaveBeenCalledTimes(1);
    parse.mockRestore();
    expect(loader.constructed).toBe(0);
  });
  it("rejects relative and non-data URIs as well as absolute ones", async () => {
    for (const uri of ["texture.png", "../secret.bin", "blob:https://x/y", "data:text/html;base64,AAAA", "HTTPS://EXAMPLE.ORG/A.BIN"]) {
      await expect(validateModelBytes(new TextEncoder().encode(JSON.stringify({ asset: { version: "2.0" }, images: [{ uri }] })), "campus.gltf", "model/gltf+json"))
        .rejects.toThrow("self-contained");
    }
  });
  it("reads and validates a file once and reuses the result for persistence", async () => {
    const file = new File([glb()], "campus.glb", { type: "model/gltf-binary" });
    const read = vi.fn(async () => glb());
    Object.defineProperty(file, "arrayBuffer", { value: read });
    const first = await loadValidatedModel(file);
    const second = await loadValidatedModel(file);
    expect(second).toBe(first);
    expect(read).toHaveBeenCalledTimes(1);
    expect(first).toMatchObject({ name: "campus.glb", mime: "model/gltf-binary", binary: true });
    const oversized = new File([new Uint8Array(MAX_MODEL_BYTES + 1)], "big.glb", { type: "model/gltf-binary" });
    const oversizedRead = vi.fn();
    Object.defineProperty(oversized, "arrayBuffer", { value: oversizedRead });
    await expect(loadValidatedModel(oversized)).rejects.toThrow(`Model must be between 1 byte and ${MAX_MODEL_SIZE_TEXT}.`);
    expect(oversizedRead).not.toHaveBeenCalled();
  });
  it("encodes base64 natively and in bounded chunks identically to the reference encoder", async () => {
    for (const size of [0, 1, 2, 3, 0x8000 - 1, 0x8000, 0x8000 * 3 + 7]) {
      const bytes = new Uint8Array(size).map((_, index) => (index * 31 + 7) % 256);
      const expected = Buffer.from(bytes).toString("base64");
      expect(bytesToBase64(bytes)).toBe(expected);
      expect(await encodeBase64(bytes)).toBe(expected);
    }
  });
  it("rejects non-canonical base64 tails for inline persisted models", async () => {
    vi.stubGlobal("crypto", webcrypto);
    let json = JSON.stringify({ asset: { version: "2.0" }, scenes: [{}], scene: 0 });
    while (json.length % 3 !== 1) json += " ";
    const bytes = new TextEncoder().encode(json);
    const digest = Buffer.from(await webcrypto.subtle.digest("SHA-256", bytes)).toString("hex");
    const canonical = Buffer.from(bytes).toString("base64");
    expect(canonical.endsWith("==")).toBe(true);
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const last = canonical[canonical.length - 3];
    const nonCanonical = canonical.slice(0, -3) + alphabet[alphabet.indexOf(last) | 1] + "==";
    expect(Buffer.from(nonCanonical, "base64")).toEqual(Buffer.from(bytes));
    const record = { campus_model_asset_id: "a", network_id: "n", model_file_name: "campus.gltf", model_mime_type: "model/gltf+json", model_size_bytes: bytes.length,
      model_sha256: digest, mapping_by_device_id: {}, source: null, created_at: "", updated_at: "" };
    expect((await decodePersistedModel({ ...record, model_data_base64: canonical }, "n", new Set())).size).toBe(bytes.length);
    await expect(decodePersistedModel({ ...record, model_data_base64: nonCanonical }, "n", new Set())).rejects.toThrow("Persisted model size or base64 encoding is invalid.");
    expect(await sha256Hex(new Uint8Array([1, 2, 3]))).toBe("039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81");
  });
});

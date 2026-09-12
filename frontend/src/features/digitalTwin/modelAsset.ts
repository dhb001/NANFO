import type { CampusModelAssetRecord } from "@/shared/types/network";

export const MAX_MODEL_BYTES = 8 * 1024 * 1024;

export async function validateModelBytes(buffer: ArrayBuffer, name: string, mime: string) {
  if (buffer.byteLength < 1 || buffer.byteLength > MAX_MODEL_BYTES) throw new Error("Model must be between 1 byte and 8 MiB.");
  const binary = name.toLowerCase().endsWith(".glb");
  if (!binary && !name.toLowerCase().endsWith(".gltf")) throw new Error("Model file must be .glb or .gltf.");
  const allowed = binary ? ["model/gltf-binary", "application/octet-stream"] : ["model/gltf+json", "application/json", "application/octet-stream"];
  if (!allowed.includes(mime.toLowerCase())) throw new Error("Model MIME type does not match its format.");
  let jsonBytes = new Uint8Array(buffer);
  if (binary) {
    const view = new DataView(buffer);
    if (buffer.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2 || view.getUint32(8, true) !== buffer.byteLength) {
      throw new Error("Invalid GLB version or declared length.");
    }
    let offset = 12;
    let chunks = 0;
    while (offset < buffer.byteLength) {
      if (offset + 8 > buffer.byteLength) throw new Error("Invalid GLB chunk.");
      const length = view.getUint32(offset, true);
      const type = view.getUint32(offset + 4, true);
      if (length % 4 || offset + 8 + length > buffer.byteLength || (chunks === 0 ? type !== 0x4e4f534a : chunks !== 1 || type !== 0x004e4942)) throw new Error("Unsupported GLB chunk.");
      if (chunks === 0) jsonBytes = new Uint8Array(buffer, offset + 8, length);
      offset += 8 + length;
      chunks += 1;
    }
  }
  let document: Record<string, unknown>;
  try { document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(jsonBytes)); }
  catch { throw new Error("Model contains invalid glTF JSON."); }
  if (!document || typeof document !== "object" || (document.asset as { version?: unknown } | undefined)?.version !== "2.0") throw new Error("Only glTF 2.0 models are supported.");
  for (const key of ["nodes", "meshes", "accessors", "bufferViews", "buffers", "materials", "textures", "images", "animations", "skins"]) {
    const entries = document[key];
    if (entries !== undefined && (!Array.isArray(entries) || entries.length > 10_000)) throw new Error("Model exceeds supported object bounds.");
    if (Array.isArray(entries)) for (const entry of entries) {
      if (!entry || typeof entry !== "object" || (entry.byteLength !== undefined && (!Number.isSafeInteger(entry.byteLength) || entry.byteLength < 0 || entry.byteLength > MAX_MODEL_BYTES)) ||
          (key === "accessors" && (!Number.isSafeInteger(entry.count) || entry.count < 0 || entry.count > 1_000_000))) throw new Error("Model exceeds supported buffer or accessor bounds.");
    }
  }
  // The persisted API stores one file only. Never fetch external resources from an imported model.
  const pending: unknown[] = [document];
  while (pending.length) {
    const item = pending.pop();
    if (!item || typeof item !== "object") continue;
    for (const [key, value] of Object.entries(item)) {
      if (key === "uri" && (typeof value !== "string" || !/^data:(?:application\/(?:octet-stream|gltf-buffer)|image\/(?:png|jpeg|webp));base64,[A-Za-z0-9+/]*={0,2}$/.test(value))) throw new Error("Model must be self-contained; external resource URIs are not supported.");
      if (typeof value === "object") pending.push(value);
    }
  }
  if (Array.isArray(document.extensionsRequired) && document.extensionsRequired.length) throw new Error("Models requiring glTF extensions are not supported for restore.");
  const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
  const gltf = await new GLTFLoader().parseAsync(binary ? buffer : new TextDecoder().decode(jsonBytes), "");
  for (const scene of gltf.scenes) scene.traverse((object) => {
    const mesh = object as import("three").Mesh;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const material of materials) {
      for (const value of Object.values(material)) if (value && typeof value === "object" && "isTexture" in value) {
        const texture = value as import("three").Texture;
        texture.dispose();
        const image = texture.image as { close?: () => void } | undefined;
        image?.close?.();
      }
      material.dispose();
    }
  });
}

export async function decodePersistedModel(asset: CampusModelAssetRecord, networkId: string, deviceIds: ReadonlySet<string>) {
  if (asset.network_id !== networkId) throw new Error("Persisted model belongs to another network.");
  const size = asset.model_size_bytes;
  const encoded = asset.model_data_base64;
  if (!Number.isInteger(size) || size < 1 || size > MAX_MODEL_BYTES || typeof encoded !== "string" || encoded.length !== 4 * Math.ceil(size / 3) || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new Error("Persisted model size or base64 encoding is invalid.");
  const raw = atob(encoded);
  if (raw.length !== size || btoa(raw) !== encoded) throw new Error("Persisted model size or base64 encoding is invalid.");
  const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  if (!/^[a-f0-9]{64}$/.test(asset.model_sha256) || hash !== asset.model_sha256) throw new Error("Persisted model SHA-256 verification failed.");
  const mapping = asset.mapping_by_device_id;
  if (!mapping || typeof mapping !== "object" || Array.isArray(mapping) || Object.keys(mapping).length > 10_000 ||
      Object.entries(mapping).some(([id, value]) => !deviceIds.has(id) || typeof value !== "string" || !value.trim() || value.length > 240)) throw new Error("Persisted mapping does not match the current complete topology.");
  await validateModelBytes(bytes.buffer, asset.model_file_name, asset.model_mime_type);
  return new File([bytes], asset.model_file_name, { type: asset.model_mime_type });
}

import type { CampusModelAssetRecord } from "@/shared/types/network";

/**
 * The only model size limit in the Twin. Mirrors the backend `_MAX_MODEL_SIZE_BYTES`
 * (backend/app/modules/network/schemas.py) so the client never sends a model the API rejects.
 */
export const MAX_MODEL_BYTES = 8 * 1024 * 1024;
export const MAX_MODEL_SIZE_TEXT = `${MAX_MODEL_BYTES / (1024 * 1024)} MiB`;

const GLB_MAGIC = 0x46546c67;
const GLB_JSON_CHUNK = 0x4e4f534a;
const GLB_BIN_CHUNK = 0x004e4942;
const SELF_CONTAINED_URI = /^data:(?:application\/(?:octet-stream|gltf-buffer)|image\/(?:png|jpeg|webp));base64,[A-Za-z0-9+/]*={0,2}$/;

export interface ValidatedModel {
  /** Exactly the validated bytes; reused for hashing/encoding so the file is read once. */
  bytes: Uint8Array<ArrayBuffer>;
  name: string;
  mime: string;
  binary: boolean;
}

function exactBuffer(input: ArrayBuffer | Uint8Array): ArrayBuffer {
  // `instanceof ArrayBuffer` is realm-specific; `isView` is not.
  if (!ArrayBuffer.isView(input)) return input;
  return input.byteOffset === 0 && input.byteLength === input.buffer.byteLength
    ? input.buffer as ArrayBuffer
    : input.slice().buffer;
}

/**
 * Structural validation with exactly one JSON parse and no network access.
 *
 * The full three.js parse happens once, in the renderer; a model is persisted only after
 * that render succeeded, so the same bytes are never parsed twice for validation.
 */
export function validateModelBytes(input: ArrayBuffer | Uint8Array, name: string, mime: string): Promise<void> {
  // Validation is synchronous CPU work; failures surface as a rejected promise, never a throw.
  return new Promise<void>((resolve) => { validateModelBytesSync(input, name, mime); resolve(); });
}

function validateModelBytesSync(input: ArrayBuffer | Uint8Array, name: string, mime: string): void {
  const buffer = exactBuffer(input);
  if (buffer.byteLength < 1 || buffer.byteLength > MAX_MODEL_BYTES) throw new Error(`Model must be between 1 byte and ${MAX_MODEL_SIZE_TEXT}.`);
  const lower = name.toLowerCase();
  const binary = lower.endsWith(".glb");
  if (!binary && !lower.endsWith(".gltf")) throw new Error("Model file must be .glb or .gltf.");
  const allowed = binary ? ["model/gltf-binary", "application/octet-stream"] : ["model/gltf+json", "application/json", "application/octet-stream"];
  if (!allowed.includes(mime.toLowerCase())) throw new Error("Model MIME type does not match its format.");
  let jsonBytes = new Uint8Array(buffer);
  if (binary) {
    const view = new DataView(buffer);
    if (buffer.byteLength < 20 || view.getUint32(0, true) !== GLB_MAGIC || view.getUint32(4, true) !== 2 || view.getUint32(8, true) !== buffer.byteLength) {
      throw new Error("Invalid GLB version or declared length.");
    }
    let offset = 12;
    let chunks = 0;
    while (offset < buffer.byteLength) {
      if (offset + 8 > buffer.byteLength) throw new Error("Invalid GLB chunk.");
      const length = view.getUint32(offset, true);
      const type = view.getUint32(offset + 4, true);
      if (length % 4 || offset + 8 + length > buffer.byteLength || (chunks === 0 ? type !== GLB_JSON_CHUNK : chunks !== 1 || type !== GLB_BIN_CHUNK)) throw new Error("Unsupported GLB chunk.");
      if (chunks === 0) jsonBytes = new Uint8Array(buffer, offset + 8, length);
      offset += 8 + length;
      chunks += 1;
    }
    if (chunks === 0) throw new Error("Invalid GLB chunk.");
  }
  let parsed: unknown;
  try { parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(jsonBytes)); }
  catch { throw new Error("Model contains invalid glTF JSON."); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || ((parsed as { asset?: { version?: unknown } }).asset)?.version !== "2.0") {
    throw new Error("Only glTF 2.0 models are supported.");
  }
  const document = parsed as Record<string, unknown>;
  for (const key of ["nodes", "meshes", "accessors", "bufferViews", "buffers", "materials", "textures", "images", "animations", "skins"]) {
    const entries = document[key];
    if (entries !== undefined && (!Array.isArray(entries) || entries.length > 10_000)) throw new Error("Model exceeds supported object bounds.");
    if (Array.isArray(entries)) for (const raw of entries as unknown[]) {
      const entry = raw && typeof raw === "object" ? raw as { byteLength?: unknown; count?: unknown } : null;
      const byteLength = entry?.byteLength, count = entry?.count;
      if (!entry || (byteLength !== undefined && (typeof byteLength !== "number" || !Number.isSafeInteger(byteLength) || byteLength < 0 || byteLength > MAX_MODEL_BYTES)) ||
          (key === "accessors" && (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0 || count > 1_000_000))) throw new Error("Model exceeds supported buffer or accessor bounds.");
    }
  }
  // One file only: never let the loader fetch external resources (absolute or relative URIs).
  const pending: unknown[] = [document];
  while (pending.length) {
    const item = pending.pop();
    if (!item || typeof item !== "object") continue;
    for (const [key, value] of Object.entries(item)) {
      if (key === "uri" && (typeof value !== "string" || !SELF_CONTAINED_URI.test(value))) throw new Error("Model must be self-contained; external resource URIs are not supported.");
      if (typeof value === "object") pending.push(value);
    }
  }
  if (Array.isArray(document.extensionsRequired) && document.extensionsRequired.length) throw new Error("Models requiring glTF extensions are not supported.");
}

/** Blob bytes without relying on `Blob.arrayBuffer` (absent in some embedded runtimes). */
export function readBlobBytes(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => (reader.result && typeof reader.result !== "string" ? resolve(reader.result) : reject(new Error("Model file cannot be read.")));
    reader.onerror = () => reject(new Error("Model file cannot be read."));
    reader.readAsArrayBuffer(blob);
  });
}

const validated = new WeakMap<Blob, Promise<ValidatedModel>>();

/**
 * Size-check, read and validate a model file once; later callers (persist) reuse the result.
 * Must succeed before any object URL is created for the file.
 */
export function loadValidatedModel(file: File): Promise<ValidatedModel> {
  const cached = validated.get(file);
  if (cached) return cached;
  const mime = file.type || "application/octet-stream";
  const result = (async () => {
    if (file.size < 1 || file.size > MAX_MODEL_BYTES) throw new Error(`Model must be between 1 byte and ${MAX_MODEL_SIZE_TEXT}.`);
    const buffer = await readBlobBytes(file);
    await validateModelBytes(buffer, file.name, mime);
    return { bytes: new Uint8Array(buffer), name: file.name, mime, binary: file.name.toLowerCase().endsWith(".glb") };
  })();
  validated.set(file, result);
  result.catch(() => validated.delete(file));
  return result;
}

const BASE64_CHUNK = 0x8000;

/** Chunked fallback: bounded argument lists, no per-byte string concatenation. */
export function bytesToBase64(bytes: Uint8Array): string {
  const parts: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += BASE64_CHUNK) {
    parts.push(String.fromCharCode.apply(null, bytes.subarray(offset, offset + BASE64_CHUNK) as unknown as number[]));
  }
  return btoa(parts.join(""));
}

/** Base64 via the browser's native encoder (FileReader), falling back to chunked encoding. */
export function encodeBase64(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  if (typeof FileReader === "undefined") return Promise.resolve(bytesToBase64(bytes));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = typeof reader.result === "string" ? reader.result : "";
      const comma = url.indexOf(",");
      if (!url.startsWith("data:") || comma < 0 || !url.slice(0, comma).endsWith(";base64")) reject(new Error("Model encoding failed."));
      else resolve(url.slice(comma + 1));
    };
    reader.onerror = () => reject(new Error("Model encoding failed."));
    reader.readAsDataURL(new Blob([bytes], { type: "application/octet-stream" }));
  });
}

export async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  if (typeof crypto === "undefined" || !crypto.subtle) throw new Error("This browser context does not support Web Crypto SHA-256.");
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  let hex = "";
  for (const value of digest) hex += value.toString(16).padStart(2, "0");
  return hex;
}

function decodeCanonicalBase64(encoded: string, size: number): Uint8Array<ArrayBuffer> {
  const invalid = () => new Error("Persisted model size or base64 encoding is invalid.");
  if (encoded.length !== 4 * Math.ceil(size / 3) || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw invalid();
  const raw = atob(encoded);
  if (raw.length !== size) throw invalid();
  // Only a padded final quantum can hide non-zero unused bits (non-canonical encoding).
  const tail = size % 3;
  if (tail && btoa(raw.slice(size - tail)) !== encoded.slice(-4)) throw invalid();
  const bytes = new Uint8Array(size);
  for (let index = 0; index < size; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

export async function decodePersistedModel(asset: CampusModelAssetRecord, networkId: string, deviceIds: ReadonlySet<string>, binaryBytes?: Uint8Array<ArrayBuffer>) {
  if (asset.network_id !== networkId) throw new Error("Persisted model belongs to another network.");
  const size = asset.model_size_bytes;
  if (!Number.isInteger(size) || size < 1 || size > MAX_MODEL_BYTES) throw new Error("Persisted model size or base64 encoding is invalid.");
  let bytes = binaryBytes;
  if (!bytes) {
    if (typeof asset.model_data_base64 !== "string") throw new Error("Persisted model size or base64 encoding is invalid.");
    bytes = decodeCanonicalBase64(asset.model_data_base64, size);
  }
  if (bytes.byteLength !== size) throw new Error("Persisted model size mismatch.");
  const hash = await sha256Hex(bytes);
  if (!/^[a-f0-9]{64}$/.test(asset.model_sha256) || hash !== asset.model_sha256) throw new Error("Persisted model SHA-256 verification failed.");
  const mapping = asset.mapping_by_device_id;
  if (!mapping || typeof mapping !== "object" || Array.isArray(mapping) || Object.keys(mapping).length > 10_000 ||
      Object.entries(mapping).some(([id, value]) => !deviceIds.has(id) || typeof value !== "string" || !value.trim() || value.length > 240)) throw new Error("Persisted mapping does not match the current complete topology.");
  await validateModelBytes(bytes, asset.model_file_name, asset.model_mime_type);
  const file = new File([bytes], asset.model_file_name, { type: asset.model_mime_type });
  // The restored bytes are already verified: persisting them later reuses this result.
  validated.set(file, Promise.resolve({ bytes, name: asset.model_file_name, mime: asset.model_mime_type, binary: asset.model_file_name.toLowerCase().endsWith(".glb") }));
  return file;
}

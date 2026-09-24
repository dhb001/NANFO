import { apiUrl } from "@/shared/lib/env";
import { ApiClientError } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import type { CampusModelAssetRecord } from "@/shared/types/network";
import { MAX_MODEL_BYTES } from "./modelAsset";

const DIGEST_ETAG = /^(?:W\/)?"(?:sha256:)?([0-9a-f]{64})"$/i;

/**
 * Digest named by an ETag (C4 `"sha256:<hex>"`), tolerating the weak form (`W/`) that
 * compressing proxies produce and the legacy bare-hex form. Opaque validators return
 * null: the SHA-256 of the body (verified by `decodePersistedModel`) is authoritative.
 */
export function etagDigest(etag: string | null): string | null {
  const match = etag?.trim().match(DIGEST_ETAG);
  return match ? match[1].toLowerCase() : null;
}

export async function downloadModelBytes(asset: CampusModelAssetRecord, signal?: AbortSignal) {
  const session = useAuthStore.getState(), context = useWorkspaceStore.getState();
  const check = () => {
    const current = useAuthStore.getState();
    if (signal?.aborted || !current.accessToken || current.endingSession || current.generation !== session.generation || context !== useWorkspaceStore.getState() || context.networkId !== asset.network_id) throw new Error("Asset session/context changed.");
  };
  if (!Number.isInteger(asset.model_size_bytes) || asset.model_size_bytes < 1 || asset.model_size_bytes > MAX_MODEL_BYTES) throw new Error("Invalid asset size.");
  const path = `/api/v1/networks/${encodeURIComponent(asset.network_id)}/campus-model-assets/${encodeURIComponent(asset.campus_model_asset_id)}/download`;
  // Identity constructs the URL. Never follow arbitrary server-supplied download paths.
  // No If-None-Match is sent (there is no local byte cache), so every read is a full body.
  let response: Response | undefined;
  for (let attempt = 0; attempt < 2; attempt++) {
    check(); const token = useAuthStore.getState().accessToken;
    response = await fetch(apiUrl(path), { headers: { Authorization: `Bearer ${token}` }, signal, cache: "no-store", redirect: "error" });
    check();
    if (response.status !== 401 || attempt) break;
    await response.body?.cancel();
    const { refreshSession } = await import("@/features/auth/session");
    if (!(useAuthStore.getState().accessToken !== token || await refreshSession())) throw new Error("Authentication required.");
  }
  if (response!.status === 304) {
    // Only reachable if an intermediary revalidated on our behalf: there are no bytes to use.
    await response!.body?.cancel();
    throw new ApiClientError("Asset download returned 304 without a local copy. Retry the restore.", "ASSET_NOT_MODIFIED", 304);
  }
  if (!response!.ok) {
    const payload = await response!.json().catch(() => null); check();
    throw new ApiClientError(payload?.errors?.message ?? "Asset download failed.", payload?.errors?.code ?? "ASSET_DOWNLOAD_FAILED", response!.status);
  }
  const length = response!.headers.get("Content-Length");
  const digest = etagDigest(response!.headers.get("ETag"));
  const type = response!.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase();
  if (type !== "application/octet-stream" || (length !== null && Number(length) !== asset.model_size_bytes) || (digest !== null && digest !== asset.model_sha256)) {
    await response!.body?.cancel(); throw new Error("Asset headers changed. Reload metadata.");
  }
  const reader = response!.body?.getReader(); if (!reader) throw new Error("Empty asset response.");
  const bytes = new Uint8Array(asset.model_size_bytes); let offset = 0;
  try {
    while (true) {
      const { value, done } = await reader.read(); check(); if (done) break;
      if (offset + value.length > bytes.length) throw new Error("Asset length mismatch.");
      bytes.set(value, offset); offset += value.length;
    }
  } finally { await reader.cancel(); }
  if (offset !== bytes.length) throw new Error("Asset length mismatch.");
  check(); return bytes;
}

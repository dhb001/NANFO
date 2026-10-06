import { apiUrl } from "@/shared/lib/env";
import { ApiClientError } from "@/shared/lib/errors";
import { etagSha256 } from "@/shared/lib/etag";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import type { CampusModelAssetRecord } from "@/shared/types/network";
import { MAX_MODEL_BYTES } from "./modelAsset";

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
    response = await fetch(apiUrl(path), { headers: { Authorization: `Bearer ${token}` }, ...(signal ? { signal } : {}), cache: "no-store", redirect: "error" });
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
    const payload: unknown = await response!.json().catch(() => null); check();
    const errors = payload && typeof payload === "object" ? (payload as { errors?: { message?: unknown; code?: unknown } | null }).errors : null;
    throw new ApiClientError(typeof errors?.message === "string" ? errors.message : "Asset download failed.",
      typeof errors?.code === "string" ? errors.code : "ASSET_DOWNLOAD_FAILED", response!.status);
  }
  const length = response!.headers.get("Content-Length");
  // Digest ETags ("sha256:<hex>", W/ weak, legacy bare hex) are a pre-check; opaque ones are ignored and the body SHA-256 stays authoritative.
  const digest = etagSha256(response!.headers.get("ETag"));
  const type = response!.headers.get("Content-Type")?.split(";")[0]?.trim().toLowerCase();
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

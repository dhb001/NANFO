import { API_BASE_URL } from "@/shared/lib/env";
import { ApiClientError } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import type { CampusModelAssetRecord } from "@/shared/types/network";

export async function downloadModelBytes(asset: CampusModelAssetRecord, signal?: AbortSignal) {
  const session = useAuthStore.getState(), context = useWorkspaceStore.getState();
  const check = () => {
    const current = useAuthStore.getState();
    if (signal?.aborted || !current.accessToken || current.endingSession || current.generation !== session.generation || context !== useWorkspaceStore.getState() || context.networkId !== asset.network_id) throw new Error("Asset session/context changed.");
  };
  if (!Number.isInteger(asset.model_size_bytes) || asset.model_size_bytes < 1 || asset.model_size_bytes > 8 * 1024 * 1024) throw new Error("Invalid asset size.");
  const path = `/api/v1/networks/${encodeURIComponent(asset.network_id)}/campus-model-assets/${encodeURIComponent(asset.campus_model_asset_id)}/download`;
  // Identity constructs the URL. Never follow arbitrary server-supplied download paths.
  let response: Response | undefined;
  for (let attempt = 0; attempt < 2; attempt++) {
    check(); const token = useAuthStore.getState().accessToken;
    response = await fetch(`${API_BASE_URL}${path}`, { headers: { Authorization: `Bearer ${token}` }, signal, cache: "no-store", redirect: "error" });
    check();
    if (response.status !== 401 || attempt) break;
    await response.body?.cancel();
    const { refreshSession } = await import("@/features/auth/session");
    if (!(useAuthStore.getState().accessToken !== token || await refreshSession())) throw new Error("Authentication required.");
  }
  if (!response!.ok) {
    const payload = await response!.json().catch(() => null); check();
    throw new ApiClientError(payload?.errors?.message ?? "Asset download failed.", payload?.errors?.code ?? "ASSET_DOWNLOAD_FAILED", response!.status);
  }
  const length = response!.headers.get("Content-Length");
  const etag = response!.headers.get("ETag");
  if (response!.headers.get("Content-Type")?.split(";")[0] !== asset.model_mime_type || (length !== null && Number(length) !== asset.model_size_bytes) || (etag !== null && etag !== `"${asset.model_sha256}"`)) {
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

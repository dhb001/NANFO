import { apiUrl } from "@/shared/lib/env";
import { ApiClientError } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { ApiEnvelope } from "@/shared/types/api";
import { ReportArtifactRef, ReportRecord } from "@/shared/types/reporting";
import { hasGeneratedArtifact } from "./logic";

export function safeReportFilename(value: string | null | undefined, mediaType: string): string {
  const extension = mediaType === "application/pdf" ? "pdf" : "csv";
  const name = (value ?? "report").split(/[\\/]/).pop()!.replace(/\.[^.]*$/, "")
    .replace(/[^a-zA-Z0-9_-]/g, "_").replace(/^_+/, "").slice(0, 100);
  return `${!name || /^(con|prn|aux|nul|com[0-9]|lpt[0-9])$/i.test(name) ? "report" : name}.${extension}`;
}

export async function downloadReport(report: ReportRecord, artifact: ReportArtifactRef, signal: AbortSignal, verifyChecksum = true) {
  const session = useAuthStore.getState(), context = useWorkspaceStore.getState();
  if (!session.accessToken || session.endingSession || context.workspaceId !== report.workspace_id || !hasGeneratedArtifact(report)
      || !report.artifacts.includes(artifact)) throw new Error("Session or artifact unavailable.");
  const assertCurrent = () => {
    if (signal.aborted || session.generation !== useAuthStore.getState().generation || useAuthStore.getState().endingSession
        || context !== useWorkspaceStore.getState()) throw new ApiClientError("Session context changed", "API_STALE_CONTEXT", 0);
  };
  // Browser allocation bound, not a claim about deployment storage limits.
  if (artifact.size_bytes > 32 * 1024 * 1024) throw new Error("Browser limit: 32 MiB.");
  const path = `/api/v1/reports/${encodeURIComponent(report.report_id)}/download?${new URLSearchParams({ workspace_id: report.workspace_id })}`;
  let response: Response | undefined;
  for (let attempt = 0; attempt < 2; attempt++) {
    assertCurrent();
    const token = useAuthStore.getState().accessToken;
    response = await fetch(apiUrl(path), { headers: { Authorization: `Bearer ${token}` }, signal, cache: "no-store", redirect: "error" });
    assertCurrent();
    if (response.status !== 401 || attempt > 0) break;
    await response.body?.cancel();
    const { refreshSession } = await import("@/features/auth/session");
    if (!(useAuthStore.getState().accessToken !== token || await refreshSession())) throw new ApiClientError("Authentication required", "HTTP_401", 401);
  }
  if (!response) throw new Error("Download unavailable.");
  if (!response.ok) {
    let payload: ApiEnvelope<unknown> | null = null;
    try { payload = await response.json() as ApiEnvelope<unknown>; } catch { /* Non-JSON proxy errors retain HTTP status. */ }
    assertCurrent();
    if (response.status === 401) useAuthStore.getState().clearSession();
    throw new ApiClientError(payload?.errors?.message ?? `Download failed (${response.status})`, payload?.errors?.code ?? `HTTP_${response.status}`, response.status);
  }
  const type = response.headers.get("Content-Type")?.split(";")[0].trim();
  const length = response.headers.get("Content-Length");
  const etag = response.headers.get("ETag");
  if (type !== artifact.media_type || (length !== null && Number(length) !== artifact.size_bytes)
      || (etag !== null && etag !== `"${artifact.checksum_sha256}"`)) {
    await response.body?.cancel();
    throw new Error("Artifact header mismatch. Refresh status.");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Download returned no bytes.");
  const bytes = new Uint8Array(artifact.size_bytes);
  let received = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      assertCurrent();
      if (done) break;
      received += value.byteLength;
      if (received > bytes.length) throw new Error("Artifact byte length mismatch.");
      bytes.set(value, received - value.byteLength);
    }
  } finally { await reader.cancel(); }
  if (received !== artifact.size_bytes) throw new Error("Artifact byte length mismatch.");
  if (verifyChecksum) {
    if (!crypto.subtle) throw new Error("Checksum verification unavailable. Use a secure browser context.");
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (hash !== artifact.checksum_sha256.toLowerCase()) throw new Error("Artifact checksum mismatch. Download blocked.");
  }
  assertCurrent();
  const disposition = response.headers.get("Content-Disposition");
  const filename = safeReportFilename(disposition?.match(/filename="([^"]*)"/i)?.[1] ?? artifact.filename, artifact.media_type);
  return { blob: new Blob([bytes], { type: artifact.media_type }), filename, size: received, checksumVerified: verifyChecksum };
}

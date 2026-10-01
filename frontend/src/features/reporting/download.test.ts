import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { downloadReport, safeReportFilename } from "./download";
import { hasGeneratedArtifact } from "./logic";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { ReportRecord } from "@/shared/types/reporting";

const bytes = new TextEncoder().encode("section,row,field,value\r\ntelemetry,0,metric,latency_ms\r\n");
const hash = Array.from(new Uint8Array(await webcrypto.subtle.digest("SHA-256", bytes)), (byte) => byte.toString(16).padStart(2, "0")).join("");
const artifact = { artifact_id: "a1", uri: "/not-followed", filename: "report.csv", media_type: "text/csv", checksum_sha256: hash, size_bytes: bytes.length, generated_at: "2026-09-11T00:00:00Z" };
const report = { report_id: "r1", workspace_id: "w1", status: "generated", artifact_version: 1, status_version: 2, snapshot_sha256: hash, artifacts: [artifact] } as ReportRecord;
const fetchMock = vi.fn();
const refresh = vi.hoisted(() => vi.fn());
vi.mock("@/features/auth/session", () => ({ refreshSession: refresh }));
const download = (value = report, verify = true) => downloadReport(value, value.artifacts[0], new AbortController().signal, verify);
function response(body: Uint8Array = bytes, headers: Record<string, string> = {}) {
  return new Response(body as BodyInit, { headers: { "Content-Type": "text/csv", "Content-Length": String(body.length), ETag: `"sha256:${hash}"`, ...headers } });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("crypto", webcrypto); vi.stubGlobal("fetch", fetchMock);
  useAuthStore.getState().setSession({ accessToken: "access", refreshToken: "refresh", userId: operatorProfile.user_id, profile: operatorProfile });
  useWorkspaceStore.setState({ workspaceId: "w1" });
  fetchMock.mockResolvedValue(response());
});
afterEach(() => vi.unstubAllGlobals());

it("downloads actual bytes with bearer, identity, length and checksum verification", async () => {
  const result = await download();
  expect(result).toMatchObject({ size: bytes.length, filename: "report.csv", checksumVerified: true });
  expect(result.blob.size).toBe(bytes.length);
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/reports/r1/download?workspace_id=w1"), expect.objectContaining({ headers: { Authorization: "Bearer access" }, redirect: "error", cache: "no-store" }));
});

it.each(["length", "hash", "mime", "etag", "empty", "overflow"])("rejects %s mismatch without offering a blob", async (kind) => {
  if (kind === "length") fetchMock.mockResolvedValue(response(bytes, { "Content-Length": "1" }));
  if (kind === "hash") fetchMock.mockResolvedValue(response(new Uint8Array(bytes.length)));
  if (kind === "mime") fetchMock.mockResolvedValue(response(bytes, { "Content-Type": "text/html" }));
  if (kind === "etag") fetchMock.mockResolvedValue(response(bytes, { ETag: `"sha256:${"0".repeat(64)}"` }));
  if (kind === "empty") fetchMock.mockResolvedValue(response(new Uint8Array(), { "Content-Length": String(bytes.length) }));
  if (kind === "overflow") fetchMock.mockResolvedValue(response(new Uint8Array(bytes.length + 1), { "Content-Length": String(bytes.length) }));
  await expect(download()).rejects.toThrow();
});

it("optionally skips browser hashing but still checks actual byte length", async () => {
  vi.stubGlobal("crypto", {});
  await expect(download()).rejects.toThrow("Checksum verification unavailable");
  fetchMock.mockResolvedValue(response());
  await expect(download(report, false)).resolves.toMatchObject({ checksumVerified: false, size: bytes.length });
});

it("rejects a response after logout or workspace switch", async () => {
  fetchMock.mockImplementation(async () => { useWorkspaceStore.setState({ workspaceId: "other" }); return response(); });
  await expect(download()).rejects.toMatchObject({ code: "API_STALE_CONTEXT" });
  useWorkspaceStore.setState({ workspaceId: "w1" });
  fetchMock.mockImplementation(async () => { useAuthStore.getState().clearSession(); return response(); });
  await expect(download()).rejects.toMatchObject({ code: "API_STALE_CONTEXT" });
});

it("preserves JSON auth errors without retrying permission denial", async () => {
  fetchMock.mockResolvedValue(Response.json({ success: false, errors: { code: "DENIED", message: "Membership revoked" } }, { status: 403 }));
  await expect(download()).rejects.toMatchObject({ code: "DENIED", status: 403 });
  expect(refresh).not.toHaveBeenCalled();
});

it("refreshes once on expired bearer and retries with the rotated token", async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 })).mockResolvedValueOnce(response());
  refresh.mockImplementation(async () => { useAuthStore.getState().replaceTokens({ accessToken: "new", refreshToken: "new-refresh" }); return true; });
  await download();
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer new");
});

it("blocks legacy, absent and unknown-version artifacts", async () => {
  for (const patch of [{ artifact_version: 0 }, { artifact_version: 2 }, { status_version: 0 }, { snapshot_sha256: null }, { artifacts: [] }]) {
    const value = { ...report, ...patch };
    expect(hasGeneratedArtifact(value)).toBe(false);
    await expect(download(value)).rejects.toThrow();
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

it("rejects oversized metadata before allocating or fetching bytes", async () => {
  const value = { ...report, artifacts: [{ ...artifact, size_bytes: 32 * 1024 * 1024 + 1 }] };
  await expect(download(value)).rejects.toThrow("Browser limit: 32 MiB");
  expect(fetchMock).not.toHaveBeenCalled();
});

it.each(["../../bad.exe", "C:\\secret\\evil.html", "CON", "\u202eevil.pdf", "\r\nname.csv", ""])("sanitizes server filename %s and enforces the media extension", (value) => {
  expect(safeReportFilename(value, "text/csv")).toMatch(/^[a-zA-Z0-9_-]+\.csv$/);
  expect(safeReportFilename(value, "application/pdf")).toMatch(/^[a-zA-Z0-9_-]+\.pdf$/);
});

it.each([
  ["current", () => `"sha256:${hash}"`],
  ["weak current", () => `W/"sha256:${hash}"`],
  ["legacy", () => `"${hash}"`],
  ["weak legacy", () => `W/"${hash}"`],
  ["upper-case digest", () => `"sha256:${hash.toUpperCase()}"`],
  ["opaque proxy validator", () => '"a1b2-proxy"'],
  ["absent", () => null],
])("accepts a %s ETag and still verifies the body SHA-256 (ADR-028 C5)", async (_name, etag) => {
  const value = etag();
  const headers = { "Content-Type": "text/csv", "Content-Length": String(bytes.length), ...(value === null ? {} : { ETag: value }) };
  fetchMock.mockResolvedValue(new Response(bytes as BodyInit, { headers }));
  await expect(download()).resolves.toMatchObject({ checksumVerified: true, size: bytes.length });
});

it.each([
  ["legacy", `"${"f".repeat(64)}"`],
  ["weak", `W/"sha256:${"e".repeat(64)}"`],
])("rejects a mismatching %s digest ETag before reading the body", async (_name, etag) => {
  fetchMock.mockResolvedValue(response(bytes, { ETag: etag }));
  await expect(download()).rejects.toThrow("Artifact header mismatch");
});

it("rejects a tampered body even when an opaque or matching validator is present", async () => {
  const tampered = new Uint8Array(bytes.length).fill(65);
  fetchMock.mockResolvedValue(response(tampered, { ETag: `W/"sha256:${hash}"` }));
  await expect(download()).rejects.toThrow("Artifact checksum mismatch");
  fetchMock.mockResolvedValue(response(tampered, { ETag: '"opaque"' }));
  await expect(download()).rejects.toThrow("Artifact checksum mismatch");
});

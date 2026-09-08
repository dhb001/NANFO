import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { apiRequest, apiRequestNoContent } from "@/shared/lib/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { operatorProfile } from "@/test/profile";

const meta = { request_id: "request-1", timestamp: "2026-09-08T00:00:00Z" };
const fetchMock = vi.fn<typeof fetch>();

describe("canonical API client", () => {
  beforeEach(() => {
    useAuthStore.getState().clearSession();
    useExecutionModeStore.getState().reset();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("returns a narrowed success with non-null generic data", async () => {
    fetchMock.mockResolvedValue(Response.json({ success: true, data: { count: 0 }, meta, errors: null }));
    const response = await apiRequest<{ count: number } | null>("/api/v1/example");
    expectTypeOf(response.success).toEqualTypeOf<true>();
    expectTypeOf(response.data).toEqualTypeOf<{ count: number }>();
    expect(response.data.count).toBe(0);
    expect(response.meta).toEqual(meta);
  });

  it.each([null, undefined])("rejects missing data (%s)", async (data) => {
    fetchMock.mockResolvedValue(Response.json({ success: true, data, meta, errors: null }));
    await expect(apiRequest("/api/v1/example")).rejects.toMatchObject({ code: "API_EMPTY_DATA" });
  });

  it("preserves canonical denial and does not refresh a 403", async () => {
    fetchMock.mockResolvedValue(Response.json({ success: false, data: null, meta,
      errors: { code: "FORBIDDEN", message: "Permission denied" } }, { status: 403 }));
    await expect(apiRequest("/api/v1/example")).rejects.toMatchObject({ code: "FORBIDDEN", status: 403 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("requires envelopes except for the explicit no-content client", async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
    await expect(apiRequest("/api/v1/example")).rejects.toMatchObject({ code: "API_EMPTY_RESPONSE" });
    await expect(apiRequestNoContent("/api/v1/example")).resolves.toBeUndefined();
  });

  it("observes authoritative mode on error responses, not a frontend default", async () => {
    expect(useExecutionModeStore.getState().mode).toBeNull();
    fetchMock.mockResolvedValue(Response.json({ success: false, data: null,
      meta: { ...meta, execution_mode: "demo" }, errors: { code: "UNSUPPORTED", message: "No real executor" } }, { status: 503 }));
    await expect(apiRequest("/api/v1/example")).rejects.toThrow("No real executor");
    expect(useExecutionModeStore.getState().mode).toBe("demo");
  });

  it("rejects a late response after a network switch", async () => {
    useAuthStore.getState().setSession({ accessToken: "access", refreshToken: "refresh", userId: operatorProfile.user_id, profile: operatorProfile });
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    const request = apiRequest("/api/v1/example", { token: "access" });
    useWorkspaceStore.getState().setNetworkId("other-network");
    resolve(Response.json({ success: true, data: { old: true }, meta, errors: null }));
    await expect(request).rejects.toMatchObject({ code: "API_STALE_CONTEXT" });
  });
});

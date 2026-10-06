import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useOrgAuthority } from "./useOrgAuthority";
import { getOrganization } from "./api";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { ApiClientError } from "@/shared/lib/errors";
import type { Organization, OrgRole } from "@/shared/types/organization";

vi.mock("./api", () => ({ getOrganization: vi.fn() }));
const get = vi.mocked(getOrganization);
function organization(orgId: string, callerRole?: OrgRole | null): Organization {
  return { org_id: orgId, name: orgId, slug: orgId, created_at: "2026-09-20T00:00:00Z", ...(callerRole === undefined ? {} : { caller_role: callerRole }) };
}
function response(org: Organization) {
  return { success: true as const, data: org, meta: { request_id: "test", timestamp: "2026-09-20", execution_time_ms: 0 }, errors: null };
}
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  get.mockReset();
  useAuthStore.getState().setSession({ accessToken: "token-1", refreshToken: "refresh-1", userId: operatorProfile.user_id, profile: operatorProfile });
});
afterEach(() => act(() => useAuthStore.getState().clearSession()));

describe("organization authority from caller_role (ADR-028 C6)", () => {
  it("resolves the caller's role with one bounded organization read, never crawling members", async () => {
    get.mockResolvedValue(response(organization("org-a", "Admin")));
    const { result } = renderHook(() => useOrgAuthority(useAuthStore((s) => s.accessToken), "org-a"), { wrapper: wrapper() });
    expect(result.current.status).toBe("loading"); expect(result.current.canAdmin).toBe(false);
    await waitFor(() => expect(result.current.canAdmin).toBe(true));
    expect(result.current.role).toBe("Admin");
    expect(get).toHaveBeenCalledTimes(1);
    expect(get.mock.calls[0].slice(0, 2)).toEqual(["token-1", "org-a"]);
    expect(get.mock.calls[0][2]).toBeInstanceOf(AbortSignal);
  });

  it("keeps the resolved role over token rotation without another read", async () => {
    get.mockResolvedValue(response(organization("org-a", "Operator")));
    const { result } = renderHook(() => useOrgAuthority(useAuthStore((s) => s.accessToken), "org-a"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.canWrite).toBe(true));
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "token-2", refreshToken: "refresh-2" }));
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "token-3", refreshToken: "refresh-3" }));
    expect(result.current.status).toBe("resolved");
    expect(result.current.canWrite).toBe(true);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("treats the uniform 404 for absent/non-member organizations as denied and transport errors as retryable", async () => {
    get.mockRejectedValueOnce(new ApiClientError("Organization not found.", "NOT_FOUND", 404));
    const { result } = renderHook(() => useOrgAuthority("token-1", "org-b"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.status).toBe("denied"));
    expect(result.current.canWrite).toBe(false);
    get.mockRejectedValueOnce(new TypeError("Offline"));
    await act(async () => { await result.current.retry(); });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.canWrite).toBe(false);
    get.mockResolvedValueOnce(response(organization("org-b", "Read-Only")));
    await act(async () => { await result.current.retry(); });
    await waitFor(() => expect(result.current.status).toBe("resolved"));
    expect(result.current.canWrite).toBe(false);
  });

  it("fails closed when an older backend omits caller_role or answers for another organization", async () => {
    get.mockResolvedValueOnce(response(organization("org-a")));
    const { result, rerender } = renderHook(({ org }) => useOrgAuthority("token-1", org), { initialProps: { org: "org-a" }, wrapper: wrapper() });
    await waitFor(() => expect(result.current.status).toBe("denied"));
    get.mockResolvedValueOnce(response(organization("org-x", "Admin")));
    rerender({ org: "org-c" });
    await waitFor(() => expect(result.current.status).toBe("denied"));
    expect(result.current.canAdmin).toBe(false);
  });

  it("cancels a read on org change and prevents a late old-org grant", async () => {
    let finish: ((value: ReturnType<typeof response>) => void) | undefined;
    let signal: AbortSignal | undefined;
    get.mockImplementation(async (_token, org, requestSignal) => {
      if (org === "org-a") { signal = requestSignal; return new Promise((resolve) => { finish = resolve; }); }
      return response(organization("org-b", "Read-Only"));
    });
    const { result, rerender } = renderHook(({ org }) => useOrgAuthority("token-1", org), { initialProps: { org: "org-a" }, wrapper: wrapper() });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    rerender({ org: "org-b" });
    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(result.current.status).toBe("resolved"));
    await act(async () => finish?.(response(organization("org-a", "Admin"))));
    expect(result.current.role).toBe("Read-Only"); expect(result.current.canAdmin).toBe(false);
  });

  it("requires global write and isolates the role from a replacement session", async () => {
    get.mockResolvedValue(response(organization("org-a", "Admin")));
    const { result } = renderHook(() => useOrgAuthority(useAuthStore((s) => s.accessToken), "org-a"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.canAdmin).toBe(true));
    act(() => useAuthStore.getState().setProfile({ ...operatorProfile, permissions: ["read:topology"] }));
    expect(result.current.canAdmin).toBe(false);
    get.mockRejectedValue(new ApiClientError("Organization not found.", "NOT_FOUND", 404));
    act(() => useAuthStore.getState().setSession({ accessToken: "other-token", refreshToken: "other-refresh", userId: "different-user", profile: { ...operatorProfile, user_id: "different-user" } }));
    expect(result.current.canAdmin).toBe(false);
    await waitFor(() => expect(result.current.status).toBe("denied"));
  });
});

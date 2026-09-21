import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useOrgAuthority } from "./useOrgAuthority";
import { listOrgMembers } from "./api";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { ApiClientError } from "@/shared/lib/errors";

vi.mock("./api", () => ({ listOrgMembers: vi.fn() }));
const list = vi.mocked(listOrgMembers);
function member(orgId: string, id: string, role = "Read-Only") { return { org_id: orgId, user_id: id, org_role: role, created_at: "2026-09-20" }; }
function response(items: ReturnType<typeof member>[], total: number) {
  return { success: true as const, data: { items, total }, meta: { request_id: "test", timestamp: "2026-09-20", execution_time_ms: 0 }, errors: null };
}
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  list.mockReset();
  useAuthStore.getState().setSession({ accessToken: "token-1", refreshToken: "refresh-1", userId: operatorProfile.user_id, profile: operatorProfile });
});
afterEach(() => act(() => useAuthStore.getState().clearSession()));

describe("automatic current membership resolution", () => {
  it("finds actor41 sequentially, stops immediately, and rechecks only its page after rotation", async () => {
    const rows = Array.from({ length: 81 }, (_, i) => member("org-a", i === 40 ? operatorProfile.user_id : `user-${i}`, i === 40 ? "Admin" : "Read-Only"));
    list.mockImplementation(async (_token, _org, page = 1, size = 20) => response(rows.slice((page - 1) * size, page * size), rows.length));
    const { result } = renderHook(() => useOrgAuthority(useAuthStore((s) => s.accessToken), "org-a"), { wrapper: wrapper() });
    expect(result.current.status).toBe("loading"); expect(result.current.canAdmin).toBe(false);
    await waitFor(() => expect(result.current.canAdmin).toBe(true));
    expect(list.mock.calls.map((call) => call[2])).toEqual([1, 2, 3]);
    expect(list.mock.calls.every((call) => call[3] === 20 && call[4] instanceof AbortSignal)).toBe(true);
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "token-2", refreshToken: "refresh-2" }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(result.current.canAdmin).toBe(true));
    expect(list.mock.calls[3].slice(0, 4)).toEqual(["token-2", "org-a", 3, 20]);
  });

  it("uses an already loaded actor page immediately without extra reads", () => {
    const { result } = renderHook(() => useOrgAuthority("token-1", "org-a", { items: [member("org-a", operatorProfile.user_id, "Admin")], total: 41, page: 3, page_size: 20 }), { wrapper: wrapper() });
    expect(result.current.canAdmin).toBe(true); expect(list).not.toHaveBeenCalled();
  });

  it("cancels a scan on org change and prevents a late old-org grant", async () => {
    let finish: ((value: ReturnType<typeof response>) => void) | undefined;
    let signal: AbortSignal | undefined;
    list.mockImplementation(async (_token, org, _page, _size, requestSignal) => {
      if (org === "org-a") { signal = requestSignal; return new Promise((resolve) => { finish = resolve; }); }
      return response([member("org-b", operatorProfile.user_id, "Read-Only")], 1);
    });
    const { result, rerender } = renderHook(({ org }) => useOrgAuthority("token-1", org), { initialProps: { org: "org-a" }, wrapper: wrapper() });
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    rerender({ org: "org-b" });
    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(result.current.status).toBe("resolved"));
    await act(async () => finish?.(response([member("org-a", operatorProfile.user_id, "Admin")], 1)));
    expect(result.current.role).toBe("Read-Only"); expect(result.current.canAdmin).toBe(false);
  });

  it("fails closed on rotation revocation and distinguishes transport errors from denial", async () => {
    list.mockResolvedValue(response([member("org-a", operatorProfile.user_id, "Admin")], 1));
    const { result } = renderHook(() => useOrgAuthority(useAuthStore((s) => s.accessToken), "org-a"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.canAdmin).toBe(true));
    list.mockRejectedValue(new ApiClientError("Membership revoked", "FORBIDDEN", 403));
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "token-2", refreshToken: "refresh-2" }));
    expect(result.current.canAdmin).toBe(false);
    await waitFor(() => expect(result.current.status).toBe("denied"));
    list.mockRejectedValue(new TypeError("Offline"));
    await act(async () => { await result.current.retry(); });
    await waitFor(() => expect(result.current.status).toBe("error")); expect(result.current.canWrite).toBe(false);
  });

  it("stops at the initial total when the actor is absent and never grants global Admin alone", async () => {
    list.mockImplementation(async (_token, org, page = 1) => response([member(org, `other-${page}`)], page === 1 ? 41 : 1000));
    const { result } = renderHook(() => useOrgAuthority("token-1", "org-a"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.status).toBe("denied"));
    expect(list.mock.calls.map((call) => call[2])).toEqual([1, 2, 3]); expect(result.current.canAdmin).toBe(false);
  });

  it("requires global write and isolates membership from a replacement session", async () => {
    list.mockResolvedValue(response([member("org-a", operatorProfile.user_id, "Admin")], 1));
    const { result } = renderHook(() => useOrgAuthority(useAuthStore((s) => s.accessToken), "org-a"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.canAdmin).toBe(true));
    act(() => useAuthStore.getState().setProfile({ ...operatorProfile, permissions: ["read:topology"] }));
    expect(result.current.role).toBe("Admin"); expect(result.current.canAdmin).toBe(false);
    act(() => useAuthStore.getState().setSession({ accessToken: "other-token", refreshToken: "other-refresh", userId: "different-user", profile: { ...operatorProfile, user_id: "different-user" } }));
    expect(result.current.canAdmin).toBe(false);
    await waitFor(() => expect(result.current.status).toBe("denied"));
  });
});

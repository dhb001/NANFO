import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { logoutSession, recoverSocketUpgrade, refreshSession } from "@/features/auth/session";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { queryClient } from "@/app/queryClient";
import { operatorProfile } from "@/test/profile";
import { apiRequest } from "@/shared/lib/api";

const envelope = (data: unknown) => Response.json({ success: true, data,
  meta: { request_id: "r", timestamp: "2026-09-08T00:00:00Z" }, errors: null });
const pair = { access_token: "access-new", refresh_token: "refresh-new", token_type: "bearer", expires_in: 900 };
const fetchMock = vi.fn<typeof fetch>();

function seedSession(userId = operatorProfile.user_id) {
  useAuthStore.getState().setSession({ accessToken: "access-old", refreshToken: "refresh-old", userId,
    profile: { ...operatorProfile, user_id: userId } });
  useWorkspaceStore.getState().setOrganizationId("org");
  useWorkspaceStore.getState().setWorkspaceId("workspace");
  useWorkspaceStore.getState().setNetworkId("network");
  queryClient.setQueryData(["private"], "secret");
  useLiveStore.getState().applyTopologyDelta({ delta_type: "add", node: { device_id: "device", hostname: "private" } });
}

describe("session lifecycle", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    seedSession();
  });
  afterEach(() => { useAuthStore.getState().clearSession(); vi.unstubAllGlobals(); });

  it("calls backend logout before clearing every session-owned store", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    useExecutionModeStore.getState().observe("production");
    const task = logoutSession();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/auth/logout"),
      expect.objectContaining({ method: "POST", headers: { Authorization: "Bearer access-old" } }));
    expect(useAuthStore.getState().accessToken).toBe("access-old");
    expect(useAuthStore.getState().endingSession).toBe(true);
    resolve(envelope({ logged_out: true }));
    await task;
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().profile).toBeNull();
    expect(useWorkspaceStore.getState().organizationId).toBeNull();
    expect(useWorkspaceStore.getState().workspaceId).toBeNull();
    expect(useWorkspaceStore.getState().networkId).toBeNull();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(useLiveStore.getState().topologyByDeviceId).toEqual({});
    expect(useExecutionModeStore.getState().mode).toBeNull();
    expect(sessionStorage.getItem("nanfo.auth.session")).toBeNull();
  });

  it("clears locally even if backend revocation fails", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    await expect(logoutSession()).rejects.toThrow("offline");
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(queryClient.getQueryData(["private"])).toBeUndefined();
    expect(useLiveStore.getState().topologyByDeviceId).toEqual({});
  });

  it("rotates both tokens in one state/storage update and shares refresh across callers", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    fetchMock.mockResolvedValueOnce(envelope(operatorProfile));
    const observed: Array<[string | null, string | null]> = [];
    const unsubscribe = useAuthStore.subscribe((state) => observed.push([state.accessToken, state.refreshToken]));
    const first = refreshSession();
    const second = refreshSession();
    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve(envelope(pair));
    expect(await first).toBe(true);
    unsubscribe();
    expect(observed.every(([access, refresh]) => access === "access-new" && refresh === "refresh-new")).toBe(true);
    expect(JSON.parse(sessionStorage.getItem("nanfo.auth.session") ?? "{}")).toMatchObject({ accessToken: "access-new", refreshToken: "refresh-new" });
    expect(localStorage.getItem("nanfo.auth.session")).toBeNull();
    expect(useWorkspaceStore.getState().networkId).toBe("network");
    expect(useAuthStore.getState().profile).toEqual(operatorProfile);
  });

  it("does not revive a logged-out session with a late refresh", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const task = refreshSession();
    useAuthStore.getState().clearSession();
    resolve(envelope(pair));
    expect(await task).toBe(false);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("logs out with the newly rotated token when logout overlaps refresh", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    fetchMock.mockResolvedValueOnce(envelope({ logged_out: true }));
    const rotation = refreshSession();
    const logout = logoutSession();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve(envelope(pair));
    await rotation;
    await logout;
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/auth/logout"),
      expect.objectContaining({ headers: { Authorization: "Bearer access-new" } }));
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("refreshes once after expired-access logout and revokes the rotated pair", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ success: false, data: null, meta: {},
      errors: { code: "UNAUTHORIZED", message: "expired" } }, { status: 401 }));
    fetchMock.mockResolvedValueOnce(envelope(pair));
    fetchMock.mockResolvedValueOnce(envelope({ logged_out: true }));
    await logoutSession();
    expect(fetchMock.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual([
      "/api/v1/auth/logout", "/api/v1/auth/refresh", "/api/v1/auth/logout",
    ]);
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/auth/logout"),
      expect.objectContaining({ headers: { Authorization: "Bearer access-new" } }));
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("reports unconfirmed revocation and clears locally when logout recovery is offline", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "expired" } }, { status: 401 }));
    fetchMock.mockRejectedValueOnce(new TypeError("Network failure"));
    await expect(logoutSession()).rejects.toThrow("revocation could not be confirmed");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(queryClient.getQueryData(["private"])).toBeUndefined();
  });

  it("does not loop when logout with the rotated token is also denied", async () => {
    const denial = () => Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "denied" } }, { status: 401 });
    fetchMock.mockResolvedValueOnce(denial()).mockResolvedValueOnce(envelope(pair)).mockResolvedValueOnce(denial());
    await expect(logoutSession()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("never logs out a new identity after a late logout recovery rotation", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockResolvedValueOnce(Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "expired" } }, { status: 401 }));
    fetchMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const task = logoutSession();
    const rejected = expect(task).rejects.toThrow("revocation could not be confirmed");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    seedSession("new-user");
    resolve(envelope(pair));
    await rejected;
    expect(useAuthStore.getState().userId).toBe("new-user");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shares upgrade auth probes and rotates only on a confirmed me 401", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    fetchMock.mockResolvedValueOnce(envelope(pair)).mockResolvedValueOnce(envelope(operatorProfile));
    const first = recoverSocketUpgrade("access-old");
    expect(recoverSocketUpgrade("access-old")).toBe(first);
    resolve(Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "expired" } }, { status: 401 }));
    expect(await first).toBe("conclusive");
    expect(useAuthStore.getState().accessToken).toBe("access-new");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it.each(["offline", "unavailable", "authorized", "forbidden"])("does not rotate on %s upgrade probe", async (outcome) => {
    if (outcome === "offline") fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    else if (outcome === "unavailable") fetchMock.mockResolvedValueOnce(Response.json({ success: false, data: null, errors: { code: "UNAVAILABLE", message: "offline" } }, { status: 503 }));
    else if (outcome === "authorized") fetchMock.mockResolvedValueOnce(envelope(operatorProfile));
    else fetchMock.mockResolvedValueOnce(Response.json({ success: false, data: null, errors: { code: "FORBIDDEN", message: "denied" } }, { status: 403 }));
    expect(await recoverSocketUpgrade("access-old")).toBe(outcome === "offline" || outcome === "unavailable" ? "inconclusive" : "conclusive");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().accessToken).toBe("access-old");
  });

  it("does not clear a new identity when the previous refresh fails", async () => {
    let reject!: (error: Error) => void;
    fetchMock.mockReturnValueOnce(new Promise((_done, fail) => { reject = fail; }));
    const task = refreshSession();
    seedSession("new-user");
    reject(new Error("revoked"));
    expect(await task).toBe(false);
    expect(useAuthStore.getState().userId).toBe("new-user");
  });

  it("resets cache and live state on context switching", () => {
    useWorkspaceStore.getState().setWorkspaceId("other");
    expect(useWorkspaceStore.getState().networkId).toBeNull();
    expect(queryClient.getQueryData(["private"])).toBeUndefined();
    expect(useLiveStore.getState().topologyByDeviceId).toEqual({});
    expect(useAuthStore.getState().accessToken).toBe("access-old");
  });

  it("refreshes concurrent REST 401s once and retries with the rotated access token", async () => {
    fetchMock.mockImplementation(async (url, options) => {
      if (String(url).endsWith("/auth/refresh")) return envelope(pair);
      if (String(url).endsWith("/auth/me")) return envelope(operatorProfile);
      if (new Headers(options?.headers).get("Authorization") === "Bearer access-old") {
        return Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "expired" } }, { status: 401 });
      }
      return envelope({ value: 42 });
    });
    const results = await Promise.all([apiRequest("/api/v1/example", { token: "access-old" }), apiRequest("/api/v1/example", { token: "access-old" })]);
    expect(results.map((result) => result.data)).toEqual([{ value: 42 }, { value: 42 }]);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it("clears the session if a retried REST request is still unauthorized", async () => {
    fetchMock.mockImplementation(async (url) => {
      if (String(url).endsWith("/auth/refresh")) return envelope(pair);
      if (String(url).endsWith("/auth/me")) return envelope(operatorProfile);
      return Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "revoked" } }, { status: 401 });
    });
    await expect(apiRequest("/api/v1/example", { token: "access-old" })).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(1);
  });
});

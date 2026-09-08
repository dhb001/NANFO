import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { operatorProfile } from "@/test/profile";

const session = { accessToken: "access", refreshToken: "refresh", userId: operatorProfile.user_id };

describe("tab-local session persistence", () => {
  beforeEach(() => { vi.resetModules(); localStorage.clear(); sessionStorage.clear(); });
  afterEach(() => vi.unstubAllGlobals());

  it("discards legacy shared credentials without importing them into this tab", async () => {
    localStorage.setItem("nanfo.auth.session", JSON.stringify(session));
    for (const key of ["accessToken", "refreshToken", "userId"]) localStorage.setItem(`nanfo.auth.${key}`, "legacy");
    const { useAuthStore } = await import("@/shared/state/auth-store");
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(Object.keys(localStorage)).toEqual([]);
    expect(sessionStorage.getItem("nanfo.auth.session")).toBeNull();
  });

  it("restores only this tab's credentials and cleans both old and current storage on logout", async () => {
    sessionStorage.setItem("nanfo.auth.session", JSON.stringify(session));
    const { useAuthStore } = await import("@/shared/state/auth-store");
    expect(useAuthStore.getState().accessToken).toBe("access");
    useAuthStore.getState().setSession({ ...session, profile: operatorProfile });
    expect(JSON.parse(sessionStorage.getItem("nanfo.auth.session") ?? "{}")).toEqual(session);
    expect(localStorage.getItem("nanfo.auth.session")).toBeNull();
    localStorage.setItem("nanfo.auth.refreshToken", "old");
    useAuthStore.getState().clearSession();
    expect(sessionStorage.getItem("nanfo.auth.session")).toBeNull();
    expect(localStorage.getItem("nanfo.auth.refreshToken")).toBeNull();
  });

  it("does not restore credentials copied into a newly opened tab", async () => {
    sessionStorage.setItem("nanfo.auth.session", JSON.stringify(session));
    vi.stubGlobal("opener", {});
    const { useAuthStore } = await import("@/shared/state/auth-store");
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(sessionStorage.getItem("nanfo.auth.session")).toBeNull();
  });
});

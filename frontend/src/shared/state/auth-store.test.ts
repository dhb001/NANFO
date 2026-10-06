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
  it("discards a session copied by a duplicated tab locally, without revoking the original's family", async () => {
    sessionStorage.setItem("nanfo.auth.session", JSON.stringify(session));
    sessionStorage.setItem("nanfo.tab.id", "tab-original");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // The original tab is alive and answers probes for its id.
    class OriginalTabChannel {
      onmessage: ((event: MessageEvent) => void) | null = null;
      postMessage(message: { type: string; tabId: string; nonce: string }) {
        if (message.type === "probe" && message.tabId === "tab-original") {
          queueMicrotask(() => this.onmessage?.(new MessageEvent("message", { data: { type: "present", tabId: "tab-original", nonce: message.nonce } })));
        }
      }
      close() {}
    }
    vi.stubGlobal("BroadcastChannel", OriginalTabChannel);
    const { useAuthStore } = await import("@/shared/state/auth-store");
    await vi.waitFor(() => expect(useAuthStore.getState().ownership).toBe("duplicate"));
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(useAuthStore.getState().notice).toBe("copied_tab");
    expect(sessionStorage.getItem("nanfo.auth.session")).toBeNull();
    expect(sessionStorage.getItem("nanfo.tab.id")).not.toBe("tab-original");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the session across a reload of the same tab (no live owner answers)", async () => {
    sessionStorage.setItem("nanfo.auth.session", JSON.stringify(session));
    sessionStorage.setItem("nanfo.tab.id", "tab-reloaded");
    class SilentChannel { onmessage = null; postMessage() {} close() {} }
    vi.stubGlobal("BroadcastChannel", SilentChannel);
    const { useAuthStore } = await import("@/shared/state/auth-store");
    await vi.waitFor(() => expect(useAuthStore.getState().ownership).toBe("owner"));
    expect(useAuthStore.getState().accessToken).toBe("access");
    expect(sessionStorage.getItem("nanfo.tab.id")).toBe("tab-reloaded");
  });
});

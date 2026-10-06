import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/shared/ui/AppShell";
import { Button } from "@/shared/ui/Button";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { queryClient } from "@/app/queryClient";
import { operatorProfile } from "@/test/profile";
import { useUiStore } from "@/shared/state/ui-store";
import { rememberFocus } from "@/shared/lib/focusRestore";
import { useEffect, useState } from "react";

vi.mock("@/features/realtime/RealtimesBridge", () => ({ RealtimeBridge: () => null }));

/** A scope control like ScopePicker; its list renders a frame later, as a loading query would. */
function ScopeSelect({ delayed = false }: { delayed?: boolean }) {
  const networkId = useWorkspaceStore((state) => state.networkId);
  const [ready, setReady] = useState(!delayed);
  useEffect(() => {
    if (ready) return;
    const timer = window.setTimeout(() => setReady(true), 20);
    return () => window.clearTimeout(timer);
  }, [ready]);
  return ready ? <select aria-label="Network scope" data-focus-key="scope-network" value={networkId ?? ""}
    onChange={(event) => { rememberFocus("scope-network"); useWorkspaceStore.getState().setNetworkId(event.target.value); }}>
    <option value="">None</option><option value="n-1">N1</option><option value="n-2">N2</option>
  </select> : <p>Loading networks</p>;
}

function renderShell(path = "/ops/audit") {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/ops" element={<AppShell />}>
      <Route path="audit" element={<div>Private audit content</div>} />
      <Route path="autonomy" element={<div>Scoped autonomy content</div>} />
      <Route path="overview" element={<input aria-label="Local draft" defaultValue="" />} />
      <Route path="tenancy" element={<ScopeSelect />} />
      <Route path="topology-analysis" element={<ScopeSelect delayed />} />
    </Route>
    <Route path="/login" element={<div>Login destination</div>} />
  </Routes></MemoryRouter>);
}

describe("authenticated shell", () => {
  beforeEach(() => useAuthStore.getState().setSession({ accessToken: "access", refreshToken: "refresh", userId: operatorProfile.user_id, profile: operatorProfile }));
  afterEach(() => { act(() => useAuthStore.getState().clearSession()); vi.unstubAllGlobals(); });

  it("denies a direct audit route and hides unauthorized navigation", () => {
    renderShell();
    expect(screen.getByText("Permission denied")).toBeInTheDocument();
    expect(screen.queryByText("Private audit content")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Audit/ })).not.toBeInTheDocument();
  });

  it("permits audit only for the backend Admin role", () => {
    useAuthStore.getState().setProfile({ ...operatorProfile, roles: ["Admin"] });
    renderShell();
    expect(screen.getByText("Private audit content")).toBeInTheDocument();
  });

  it("gates autonomy navigation and direct access on read:telemetry", () => {
    useAuthStore.getState().setProfile({ ...operatorProfile, permissions: ["read:topology"] });
    renderShell("/ops/autonomy");
    expect(screen.getByText("Permission denied")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Autonomy/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Scoped autonomy content")).not.toBeInTheDocument();
    act(() => useAuthStore.getState().setProfile(operatorProfile));
    expect(screen.getByRole("link", { name: /Autonomy/ })).toBeInTheDocument();
    expect(screen.getByText("Scoped autonomy content")).toBeInTheDocument();
  });

  it("disables denied actions without invoking them", async () => {
    useAuthStore.getState().setProfile({ ...operatorProfile, permissions: ["read:topology"] });
    const onClick = vi.fn();
    render(<Button permission="write:config" onClick={onClick}>Execute</Button>);
    const button = screen.getByRole("button", { name: "Execute" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("the actual logout button revokes the backend session and clears cache and context", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ success: true, data: { logged_out: true }, meta: {}, errors: null }));
    vi.stubGlobal("fetch", fetchMock);
    useWorkspaceStore.getState().setWorkspaceId("private-workspace");
    queryClient.setQueryData(["private"], "data");
    renderShell("/ops/overview");
    await userEvent.click(screen.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(screen.getByText("Login destination")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/auth/logout"), expect.objectContaining({ method: "POST" }));
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useWorkspaceStore.getState().workspaceId).toBeNull();
    expect(queryClient.getQueryData(["private"])).toBeUndefined();
  });

  it("remounts local feature state when switching network context", async () => {
    renderShell("/ops/overview");
    await userEvent.type(screen.getByLabelText("Local draft"), "old-network-secret");
    act(() => useWorkspaceStore.getState().setNetworkId("new-network"));
    expect(screen.getByLabelText("Local draft")).toHaveValue("");
  });

  it.each([["tenancy", "renders at once"], ["topology-analysis", "renders after loading"]])(
    "returns focus to the scope control after a switch remounts the workspace (%s: %s)", async (route) => {
      renderShell(`/ops/${route}`);
      const before = await screen.findByLabelText("Network scope");
      before.focus();
      await userEvent.selectOptions(before, "n-2");
      const after = await screen.findByLabelText("Network scope");
      expect(after).not.toBe(before);
      await waitFor(() => expect(after).toHaveFocus());
      expect(after).toHaveValue("n-2");
    });

  it("does not steal focus the operator moved elsewhere during the switch", async () => {
    renderShell("/ops/topology-analysis");
    const before = await screen.findByLabelText("Network scope");
    await userEvent.selectOptions(before, "n-1");
    screen.getByRole("button", { name: "Logout" }).focus();
    await screen.findByLabelText("Network scope");
    await act(() => new Promise((done) => setTimeout(done, 50)));
    expect(screen.getByRole("button", { name: "Logout" })).toHaveFocus();
  });

  it("reports unconfirmed revocation when logout recovery cannot reach the backend", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({ success: false, data: null, errors: { code: "UNAUTHORIZED", message: "expired" } }, { status: 401 }))
      .mockRejectedValueOnce(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchMock);
    renderShell("/ops/overview");
    await userEvent.click(screen.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(screen.getByText("Login destination")).toBeInTheDocument());
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ title: "Signed out locally", tone: "warn" });
    expect(useUiStore.getState().toasts.at(-1)?.description).toContain("revocation could not be confirmed");
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});

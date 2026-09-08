import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionGate } from "@/features/auth/SessionGate";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";

const fetchMock = vi.fn<typeof fetch>();
function renderGate() {
  render(<MemoryRouter initialEntries={["/ops"]}><Routes>
    <Route path="/ops" element={<SessionGate><div>Protected workspace</div></SessionGate>} />
    <Route path="/login" element={<div>Login required</div>} />
  </Routes></MemoryRouter>);
}

describe("restored session verification", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().setSession({ accessToken: "restored", refreshToken: "refresh", userId: operatorProfile.user_id, profile: operatorProfile });
    useAuthStore.setState({ profile: null });
  });
  afterEach(() => { act(() => useAuthStore.getState().clearSession()); vi.unstubAllGlobals(); });

  it("does not expose protected children before me confirms permissions", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    renderGate();
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
    expect(screen.getByText("Verifying session")).toBeInTheDocument();
    await act(async () => resolve(Response.json({ success: true, data: operatorProfile, meta: {}, errors: null })));
    expect(screen.getByText("Protected workspace")).toBeInTheDocument();
    expect(useAuthStore.getState().profile).toEqual(operatorProfile);
  });

  it("requires login when me and rotated-session refresh are revoked", async () => {
    fetchMock.mockImplementation(async () => Response.json({ success: false, data: null, meta: {},
      errors: { code: "UNAUTHORIZED", message: "Session revoked" } }, { status: 401 }));
    renderGate();
    await waitFor(() => expect(screen.getByText("Login required")).toBeInTheDocument());
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(1);
  });
});

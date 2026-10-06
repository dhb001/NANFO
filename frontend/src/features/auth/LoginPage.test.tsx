import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "@/features/auth/LoginPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { operatorProfile } from "@/test/profile";

const navigateMock = vi.fn();
const mutateAsyncMock = vi.fn();
const getProfileMock = vi.fn();
const logoutMock = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/features/auth/hooks", () => ({
  useLogin: () => ({
    mutateAsync: mutateAsyncMock,
    isPending: false,
    isError: false,
    error: null,
  }),
}));

vi.mock("@/features/auth/api", () => ({
  getProfile: (...args: unknown[]) => getProfileMock(...args),
  logout: (...args: unknown[]) => logoutMock(...args),
  refresh: vi.fn(),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      userId: null,
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });
    mutateAsyncMock.mockResolvedValue({
      access_token: "access-1",
      refresh_token: "refresh-1",
      token_type: "bearer",
      expires_in: 900,
    });
  });

  it("stores session and navigates when profile fetch succeeds", async () => {
    getProfileMock.mockResolvedValue({ ...operatorProfile, user_id: "user-1" });
    const user = userEvent.setup();
    render(<LoginPage />);

    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await user.type(screen.getByLabelText("Email"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "test-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(useAuthStore.getState().accessToken).toBe("access-1");
      expect(useAuthStore.getState().refreshToken).toBe("refresh-1");
      expect(useAuthStore.getState().userId).toBe("user-1");
      expect(useAuthStore.getState().profile?.roles).toEqual(operatorProfile.roles);
      expect(useAuthStore.getState().profile?.permissions).toEqual(operatorProfile.permissions);
      expect(navigateMock).toHaveBeenCalledWith("/ops/overview");
    });
  });

  it("clears session and shows toast when profile fetch fails", async () => {
    getProfileMock.mockRejectedValue(new Error("profile failed"));
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "test-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(useAuthStore.getState().accessToken).toBeNull();
      expect(useAuthStore.getState().refreshToken).toBeNull();
      expect(useAuthStore.getState().userId).toBeNull();
    });
    expect(navigateMock).not.toHaveBeenCalled();
    const latestToast = useUiStore.getState().toasts.at(-1);
    expect(latestToast?.title).toBe("Profile lookup failed");
  });

  it("does not persist a partial session while the profile request is pending", async () => {
    let resolve!: (profile: typeof operatorProfile) => void;
    getProfileMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "operator@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "test-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(screen.getByRole("button", { name: "Signing In..." })).toBeDisabled();
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(sessionStorage.getItem("nanfo.auth.session")).toBeNull();
    await act(async () => resolve(operatorProfile));
    expect(useAuthStore.getState().profile).toEqual(operatorProfile);
  });
  it("revokes this tab's previous session before signing in again", async () => {
    useAuthStore.getState().setSession({ accessToken: "old-access", refreshToken: "old-refresh", userId: "user-0", profile: { ...operatorProfile, user_id: "user-0" } });
    logoutMock.mockResolvedValue({ logged_out: true });
    getProfileMock.mockResolvedValue({ ...operatorProfile, user_id: "user-1" });
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText("Email"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "test-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(useAuthStore.getState().accessToken).toBe("access-1"));
    expect(logoutMock).toHaveBeenCalledWith("old-access");
    expect(logoutMock.mock.invocationCallOrder[0]).toBeLessThan(mutateAsyncMock.mock.invocationCallOrder[0]);
    expect(useAuthStore.getState().userId).toBe("user-1");
    expect(useUiStore.getState().toasts).toEqual([]);
  });

  it("still signs in, with a warning, when the previous revocation cannot be confirmed", async () => {
    useAuthStore.getState().setSession({ accessToken: "old-access", refreshToken: "old-refresh", userId: "user-0", profile: { ...operatorProfile, user_id: "user-0" } });
    logoutMock.mockRejectedValue(new TypeError("offline"));
    getProfileMock.mockResolvedValue({ ...operatorProfile, user_id: "user-1" });
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText("Email"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "test-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/ops/overview"));
    expect(useAuthStore.getState().accessToken).toBe("access-1");
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ tone: "warn", title: "Previous session not confirmed revoked" });
  });

  it("explains why a copied tab must sign in separately", () => {
    useAuthStore.setState({ notice: "copied_tab" });
    render(<LoginPage />);
    expect(screen.getByRole("status")).toHaveTextContent("copied from another NANFO tab");
    act(() => useAuthStore.setState({ notice: null }));
  });
});

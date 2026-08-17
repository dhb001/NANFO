import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "@/features/auth/LoginPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";

const navigateMock = vi.fn();
const mutateAsyncMock = vi.fn();
const getProfileMock = vi.fn();

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
    getProfileMock.mockResolvedValue({ user_id: "user-1" });
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(useAuthStore.getState().accessToken).toBe("access-1");
      expect(useAuthStore.getState().refreshToken).toBe("refresh-1");
      expect(useAuthStore.getState().userId).toBe("user-1");
      expect(navigateMock).toHaveBeenCalledWith("/ops/overview");
    });
  });

  it("clears session and shows toast when profile fetch fails", async () => {
    getProfileMock.mockRejectedValue(new Error("profile failed"));
    const user = userEvent.setup();
    render(<LoginPage />);

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
});

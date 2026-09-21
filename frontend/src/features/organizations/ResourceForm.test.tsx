import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeviceForm } from "@/features/overview/InventoryForms";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";

afterEach(() => act(() => useAuthStore.getState().clearSession()));
describe("inventory draft lifecycle", () => {
  it("preserves drafts and an in-flight payload over token rotation", async () => {
    useAuthStore.getState().setSession({ accessToken: "old", refreshToken: "refresh", userId: operatorProfile.user_id, profile: operatorProfile });
    let finish: (() => void) | undefined;
    const save = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const refresh = vi.fn(async () => undefined);
    const { rerender } = render(<DeviceForm onSave={save} onRefresh={refresh} />);
    fireEvent.change(screen.getByLabelText("Hostname"), { target: { value: "operator-router" } });
    fireEvent.change(screen.getByLabelText("Device type"), { target: { value: "router" } });
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "new", refreshToken: "new-refresh" }));
    rerender(<DeviceForm onSave={save} onRefresh={refresh} />);
    expect(screen.getByLabelText("Hostname")).toHaveValue("operator-router");
    fireEvent.submit(screen.getByRole("form", { name: "Create device" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "newer", refreshToken: "newer-refresh" }));
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0]).toEqual([{ hostname: "operator-router", device_type: "router", ip_address: null, vendor: null, model: null, location_hint: null, spatial_ref_id: null }]);
    await act(async () => finish?.());
    await waitFor(() => expect(screen.getByLabelText("Hostname")).toHaveValue(""));
  });
});

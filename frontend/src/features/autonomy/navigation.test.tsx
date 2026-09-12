import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { HotkeyLayer } from "@/shared/ui/HotkeyLayer";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { operatorProfile } from "@/test/profile";

describe("autonomy keyboard authorization", () => {
  beforeEach(() => {
    useAuthStore.setState({ profile: { ...operatorProfile, permissions: [] } });
    useUiStore.setState({ commandPaletteOpen: false });
  });
  it("checks current permissions before navigation and ignores approval inputs", () => {
    render(<MemoryRouter initialEntries={["/ops/overview"]}>
      <HotkeyLayer />
      <input aria-label="Approval field" />
      <Routes>
        <Route path="/ops/overview" element={<div>Overview destination</div>} />
        <Route path="/ops/autonomy" element={<div>Autonomy destination</div>} />
      </Routes>
    </MemoryRouter>);
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "n" });
    expect(screen.getByText("Overview destination")).toBeInTheDocument();
    act(() => useAuthStore.setState({ profile: operatorProfile }));
    fireEvent.keyDown(screen.getByLabelText("Approval field"), { key: "n" });
    expect(screen.getByText("Overview destination")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "n" });
    expect(screen.getByText("Autonomy destination")).toBeInTheDocument();
  });
});

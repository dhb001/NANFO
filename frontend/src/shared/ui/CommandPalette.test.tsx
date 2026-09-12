import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CommandPalette } from "@/shared/ui/CommandPalette";
import { useUiStore } from "@/shared/state/ui-store";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";

describe("CommandPalette", () => {
  beforeEach(() => useAuthStore.setState({ profile: operatorProfile }));
  it.each([true, false])("gates the autonomy command by read permission (%s)", async (permitted) => {
    useAuthStore.setState({ profile: { ...operatorProfile, permissions: permitted ? ["read:telemetry"] : [] } });
    useUiStore.setState({ commandPaletteOpen: true });
    render(<MemoryRouter><CommandPalette /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Search commands"), "autonomy");
    expect(screen.queryByText("Go to Autonomy") !== null).toBe(permitted);
  });
  it("filters commands and closes on escape", async () => {
    const user = userEvent.setup();

    useUiStore.setState({
      commandPaletteOpen: true,
      toasts: [],
    });

    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    );

    const search = screen.getByLabelText("Search commands");
    await user.type(search, "telemetry");

    expect(screen.getByText("Go to Telemetry")).toBeInTheDocument();
    expect(screen.queryByText("Go to Simulation")).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(useUiStore.getState().commandPaletteOpen).toBe(false);
  });

  it("includes alerts lifecycle navigation alias", async () => {
    const user = userEvent.setup();

    useUiStore.setState({
      commandPaletteOpen: true,
      toasts: [],
    });

    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    );

    const search = screen.getByLabelText("Search commands");
    await user.type(search, "alerts");

    expect(screen.getByText("Go to Alerts Lifecycle")).toBeInTheDocument();
  });

  it("includes plugins navigation command", async () => {
    useAuthStore.getState().setProfile({ ...operatorProfile, roles: ["Admin"] });
    const user = userEvent.setup();

    useUiStore.setState({
      commandPaletteOpen: true,
      toasts: [],
    });

    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    );

    const search = screen.getByLabelText("Search commands");
    await user.type(search, "plugins");

    expect(screen.getByText("Go to Plugins")).toBeInTheDocument();
  });

  it("includes reports navigation command", async () => {
    const user = userEvent.setup();

    useUiStore.setState({
      commandPaletteOpen: true,
      toasts: [],
    });

    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    );

    const search = screen.getByLabelText("Search commands");
    await user.type(search, "reports");

    expect(screen.getByText("Go to Reports")).toBeInTheDocument();
  });
});

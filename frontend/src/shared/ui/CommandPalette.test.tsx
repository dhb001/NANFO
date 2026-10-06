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

  it("exposes combobox/listbox semantics with an active descendant and keeps focus in the input (ADR-028)", async () => {
    const user = userEvent.setup();
    useUiStore.setState({ commandPaletteOpen: true, toasts: [] });
    render(<MemoryRouter><CommandPalette /></MemoryRouter>);
    const combobox = screen.getByRole("combobox", { name: "Search commands" });
    const listbox = screen.getByRole("listbox", { name: "Commands" });
    expect(combobox).toHaveFocus();
    expect(combobox).toHaveAttribute("aria-controls", listbox.id);
    expect(combobox).toHaveAttribute("aria-expanded", "true");
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(combobox).toHaveAttribute("aria-activedescendant", options[0].id);
    await user.keyboard("{ArrowDown}");
    expect(combobox).toHaveAttribute("aria-activedescendant", options[1].id);
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(options[0]).toHaveAttribute("aria-selected", "false");
    await user.keyboard("{End}");
    expect(combobox).toHaveAttribute("aria-activedescendant", options.at(-1)!.id);
    await user.keyboard("{Home}");
    expect(combobox).toHaveAttribute("aria-activedescendant", options[0].id);
    await user.tab();
    expect(combobox).toHaveFocus();
    await user.type(combobox, "zzz-no-match");
    expect(screen.getByRole("status")).toHaveTextContent("No commands match this filter.");
    expect(combobox).toHaveAttribute("aria-expanded", "false");
    expect(combobox).not.toHaveAttribute("aria-activedescendant");
  });
});

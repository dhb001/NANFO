import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CommandPalette } from "@/shared/ui/CommandPalette";
import { useUiStore } from "@/shared/state/ui-store";

describe("CommandPalette", () => {
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
});

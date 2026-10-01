import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { COMBOBOX_OVERSCAN, COMBOBOX_VISIBLE_ROWS } from "./comboboxWindow";
import { VirtualizedNodeCombobox } from "./VirtualizedNodeCombobox";

const MANY = Array.from({ length: 12_800 }, (_, index) => ({ id: `device-${String(index).padStart(5, "0")}`, label: `host-${String(index).padStart(5, "0")} (switch)` }));

function Harness({ options = MANY, initial = null, onSelect = vi.fn() }: { options?: typeof MANY; initial?: string | null; onSelect?: (id: string | null) => void }) {
  const [selected, setSelected] = useState<string | null>(initial);
  return (
    <VirtualizedNodeCombobox label="Inspect Node" ariaLabel="Inspect node" options={options} selectedId={selected}
      onSelect={(id) => { onSelect(id); setSelected(id); }} />
  );
}

describe("VirtualizedNodeCombobox", () => {
  it("renders only a bounded window of a 12,800-node list with full set size", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox", { name: "Inspect node" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.click(input);
    const listbox = screen.getByRole("listbox", { name: "Matching nodes" });
    const rendered = within(listbox).getAllByRole("option");
    expect(rendered.length).toBeLessThanOrEqual(COMBOBOX_VISIBLE_ROWS + 2 * COMBOBOX_OVERSCAN);
    expect(rendered[0]).toHaveAttribute("aria-setsize", "12800");
    expect(rendered[0]).toHaveAttribute("aria-posinset", "1");
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    expect(screen.getByText("12800 matching nodes")).toBeInTheDocument();
  });

  it("filters while typing and selects the first match with Enter (keyboard alternative to 3D picking)", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = screen.getByRole("combobox", { name: "Inspect node" });
    await user.type(input, "device-12345");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["host-12345 (switch)"]);
    expect(input).toHaveAttribute("aria-activedescendant", screen.getByRole("option").id);
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("device-12345");
    expect(input).toHaveValue("host-12345 (switch)");
    expect(input).toHaveAttribute("data-selected-node-id", "device-12345");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Selected host-12345 (switch)")).toBeInTheDocument();
  });

  it("moves through the virtual window with the arrow, Page and End keys and keeps the active option rendered", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = screen.getByRole("combobox", { name: "Inspect node" });
    input.focus();
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).not.toHaveAttribute("aria-activedescendant");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(document.getElementById(input.getAttribute("aria-activedescendant") ?? "")).toHaveTextContent("host-00001 (switch)");
    await user.keyboard("{End}");
    const last = document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(last).toHaveTextContent("host-12799 (switch)");
    expect(last).toHaveAttribute("aria-posinset", "12800");
    await user.keyboard("{PageUp}{Enter}");
    expect(onSelect).toHaveBeenLastCalledWith(`device-${String(12_799 - COMBOBOX_VISIBLE_ROWS).padStart(5, "0")}`);
  });

  it("opens on the current selection, closes with Escape without changing it, and clears via a labelled button", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness options={MANY.slice(0, 50)} initial="device-00030" onSelect={onSelect} />);
    const input = screen.getByRole("combobox", { name: "Inspect node" });
    expect(input).toHaveValue("host-00030 (switch)");
    await user.click(input);
    expect(document.getElementById(input.getAttribute("aria-activedescendant") ?? "")).toHaveAttribute("aria-selected", "true");
    await user.keyboard("zzz");
    expect(screen.getByText("No matching nodes")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveValue("host-00030 (switch)");
    expect(onSelect).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Clear node selection" }));
    expect(onSelect).toHaveBeenCalledWith(null);
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("data-selected-node-id", "");
  });

  it("selects an option with the pointer without losing focus", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness options={MANY.slice(0, 5)} onSelect={onSelect} />);
    const input = screen.getByRole("combobox", { name: "Inspect node" });
    await user.click(input);
    await user.click(screen.getByRole("option", { name: "host-00003 (switch)" }));
    expect(onSelect).toHaveBeenCalledWith("device-00003");
    expect(input).toHaveFocus();
  });
});

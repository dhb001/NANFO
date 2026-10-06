import { describe, expect, it } from "vitest";
import {
  COMBOBOX_OVERSCAN,
  COMBOBOX_ROW_HEIGHT,
  COMBOBOX_VISIBLE_ROWS,
  buildSearchIndex,
  filterIndexed,
  filterOptions,
  isComboboxKey,
  moveActive,
  nodeComboboxOptions,
  scrollToIndex,
  visibleWindow,
} from "./comboboxWindow";

const options = [
  { id: "00000000-0000-0000-0000-000000000444", label: "edge-1 (switch)" },
  { id: "00000000-0000-0000-0000-000000000445", label: "Core-1 (router)" },
  { id: "ap-7", label: "lobby (wireless_ap)" },
];

describe("comboboxWindow", () => {
  it("filters case-insensitively by hostname, type or device id and keeps identity for an empty query", () => {
    const index = buildSearchIndex(options);
    expect(filterIndexed(index, "")).toBe(options);
    expect(filterIndexed(index, "   ")).toBe(options);
    expect(filterIndexed(index, "CORE").map((option) => option.id)).toEqual(["00000000-0000-0000-0000-000000000445"]);
    expect(filterIndexed(index, "router").map((option) => option.label)).toEqual(["Core-1 (router)"]);
    expect(filterIndexed(index, "000000000444").map((option) => option.label)).toEqual(["edge-1 (switch)"]);
    expect(filterIndexed(index, "nothing-matches")).toEqual([]);
    expect(filterOptions(options, "wireless").map((option) => option.id)).toEqual(["ap-7"]);
  });

  it("natural-sorts inspector options with a deterministic id tie-break", () => {
    const sorted = nodeComboboxOptions([
      { id: "b", hostname: "edge-10", type: "switch" },
      { id: "c", hostname: "edge-2", type: "switch" },
      { id: "a", hostname: "Edge-2", type: "switch" },
    ]);
    expect(sorted.map((option) => option.id)).toEqual(["a", "c", "b"]);
    expect(sorted[0]).toEqual({ id: "a", label: "Edge-2 (switch)" });
  });

  it("windows a fixed-height list with overscan and clamps at both ends", () => {
    expect(visibleWindow(0, 0)).toEqual({ start: 0, end: 0 });
    expect(visibleWindow(12_800, 0)).toEqual({ start: 0, end: COMBOBOX_VISIBLE_ROWS + COMBOBOX_OVERSCAN });
    const middle = visibleWindow(12_800, 100 * COMBOBOX_ROW_HEIGHT);
    expect(middle).toEqual({ start: 100 - COMBOBOX_OVERSCAN, end: 100 + COMBOBOX_VISIBLE_ROWS + COMBOBOX_OVERSCAN });
    expect(middle.end - middle.start).toBeLessThanOrEqual(COMBOBOX_VISIBLE_ROWS + 2 * COMBOBOX_OVERSCAN);
    expect(visibleWindow(20, 10_000 * COMBOBOX_ROW_HEIGHT)).toEqual({ start: 19 - COMBOBOX_OVERSCAN, end: 20 });
    expect(visibleWindow(5, -50)).toEqual({ start: 0, end: 5 });
  });

  it("scrolls the minimum needed to reveal the active row", () => {
    const viewport = COMBOBOX_VISIBLE_ROWS * COMBOBOX_ROW_HEIGHT;
    expect(scrollToIndex(3, 0)).toBe(0);
    expect(scrollToIndex(COMBOBOX_VISIBLE_ROWS, 0)).toBe((COMBOBOX_VISIBLE_ROWS + 1) * COMBOBOX_ROW_HEIGHT - viewport);
    expect(scrollToIndex(2, 10 * COMBOBOX_ROW_HEIGHT)).toBe(2 * COMBOBOX_ROW_HEIGHT);
    expect(scrollToIndex(12_799, 0)).toBe(12_800 * COMBOBOX_ROW_HEIGHT - viewport);
  });

  it("moves the active option for every navigation key and ignores other keys", () => {
    expect(moveActive(-1, "ArrowDown", 10)).toBe(0);
    expect(moveActive(9, "ArrowDown", 10)).toBe(9);
    expect(moveActive(-1, "ArrowUp", 10)).toBe(9);
    expect(moveActive(0, "ArrowUp", 10)).toBe(0);
    expect(moveActive(4, "Home", 10)).toBe(0);
    expect(moveActive(4, "End", 10)).toBe(9);
    expect(moveActive(1, "PageDown", 20)).toBe(1 + COMBOBOX_VISIBLE_ROWS);
    expect(moveActive(15, "PageDown", 20)).toBe(19);
    expect(moveActive(3, "PageUp", 20)).toBe(0);
    expect(moveActive(3, "End", 0)).toBe(-1);
    expect(isComboboxKey("PageDown")).toBe(true);
    expect(isComboboxKey("Enter")).toBe(false);
  });
});

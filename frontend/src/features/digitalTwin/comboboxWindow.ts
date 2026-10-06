/** Pure filtering/windowing for the virtualized node combobox (fixed row height). */

export interface ComboboxOption {
  id: string;
  label: string;
}

export const COMBOBOX_ROW_HEIGHT = 32;
export const COMBOBOX_VISIBLE_ROWS = 8;
export const COMBOBOX_OVERSCAN = 4;

const LABEL_COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Inspector options `<hostname> (<type>)`, natural-sorted (edge-2 before edge-10), ties by id. */
export function nodeComboboxOptions(nodes: ReadonlyArray<{ id: string; hostname: string; type: string }>): ComboboxOption[] {
  return nodes
    .map((node) => ({ id: node.id, label: `${node.hostname} (${node.type})` }))
    .sort((left, right) => LABEL_COLLATOR.compare(left.label, right.label) || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0));
}

export interface ComboboxSearchIndex<T extends ComboboxOption> {
  options: readonly T[];
  /** Lower-cased `label \u0000 id` per option, built once per option list (not per keystroke). */
  haystacks: readonly string[];
}

export function buildSearchIndex<T extends ComboboxOption>(options: readonly T[]): ComboboxSearchIndex<T> {
  return { options, haystacks: options.map((option) => `${option.label}\u0000${option.id}`.toLowerCase()) };
}

/** Case-insensitive substring match on label or id; an empty query keeps every option. */
export function filterIndexed<T extends ComboboxOption>(index: ComboboxSearchIndex<T>, query: string): readonly T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return index.options;
  const matches: T[] = [];
  index.haystacks.forEach((haystack, position) => {
    const option = index.options[position];
    if (option && haystack.includes(needle)) matches.push(option);
  });
  return matches;
}

export function filterOptions<T extends ComboboxOption>(options: readonly T[], query: string): readonly T[] {
  return filterIndexed(buildSearchIndex(options), query);
}

export function visibleWindow(count: number, scrollTop: number, rowHeight = COMBOBOX_ROW_HEIGHT, visibleRows = COMBOBOX_VISIBLE_ROWS, overscan = COMBOBOX_OVERSCAN): { start: number; end: number } {
  if (count <= 0) return { start: 0, end: 0 };
  const first = Math.min(count - 1, Math.max(0, Math.floor(Math.max(0, scrollTop) / rowHeight)));
  return { start: Math.max(0, first - overscan), end: Math.min(count, first + visibleRows + overscan) };
}

/** Smallest scroll change that brings `index` fully into the viewport. */
export function scrollToIndex(index: number, scrollTop: number, rowHeight = COMBOBOX_ROW_HEIGHT, visibleRows = COMBOBOX_VISIBLE_ROWS): number {
  const top = index * rowHeight;
  const bottom = top + rowHeight;
  const viewport = visibleRows * rowHeight;
  if (top < scrollTop) return top;
  if (bottom > scrollTop + viewport) return bottom - viewport;
  return scrollTop;
}

export type ComboboxKey = "ArrowDown" | "ArrowUp" | "Home" | "End" | "PageDown" | "PageUp";

export function isComboboxKey(key: string): key is ComboboxKey {
  return key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End" || key === "PageDown" || key === "PageUp";
}

export function moveActive(active: number, key: ComboboxKey, count: number, page = COMBOBOX_VISIBLE_ROWS): number {
  if (count <= 0) return -1;
  switch (key) {
    case "ArrowDown": return active < 0 ? 0 : Math.min(count - 1, active + 1);
    case "ArrowUp": return active < 0 ? count - 1 : Math.max(0, active - 1);
    case "Home": return 0;
    case "End": return count - 1;
    case "PageDown": return Math.min(count - 1, Math.max(0, active) + page);
    case "PageUp": return Math.max(0, Math.max(0, active) - page);
    default: return active;
  }
}

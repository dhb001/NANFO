import { expect, type Locator, type Page } from "@playwright/test";

// The Twin's "Inspect node" control is an ARIA combobox with a virtualized listbox
// (FE-Twin): select by typing a hostname/type/device id and pressing Enter.

export function inspectNodeInput(page: Page): Locator {
  return page.getByLabel("Inspect node");
}

export async function inspectNode(page: Page, query: string): Promise<void> {
  const input = inspectNodeInput(page);
  await input.fill(query);
  await input.press("Enter");
}

export async function expectInspectedNode(page: Page, deviceId: string): Promise<void> {
  await expect(inspectNodeInput(page)).toHaveAttribute("data-selected-node-id", deviceId);
}

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Options currently offered for `text` (the listbox shows only matches). */
export async function nodeOptions(page: Page, text: string): Promise<Locator> {
  await inspectNodeInput(page).fill(text);
  return page.getByRole("option", { name: new RegExp(escapeRegExp(text)) });
}

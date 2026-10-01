import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test("CSS palette entry, exit, reopening and reduced motion preserve keyboard navigation", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  await loginFromUi(page);
  const toggle = page.getByRole("button", { name: "Toggle command palette" });
  await toggle.click();
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS("animation-name", "palette-backdrop-enter");
  await expect(page.getByLabel("Search commands")).toBeFocused();
  // Combobox pattern: options are not tab stops, focus stays in the search input.
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByLabel("Search commands")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Search commands")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  const tenancy = dialog.getByRole("option", { name: /Go to Tenancy/ });
  await expect(tenancy).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("combobox", { name: "Search commands" })).toHaveAttribute("aria-activedescendant", (await tenancy.getAttribute("id"))!);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".command-palette-backdrop")).toHaveCount(0);
  await expect(toggle).toBeFocused();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await toggle.click();
  await expect(dialog).toHaveCSS("animation-name", "none");
  await expect(dialog.locator(".command-palette-surface")).toHaveCSS("animation-name", "none");
  await expect(page.locator(".page-heading")).toHaveCSS("animation-name", "none");
  await page.getByLabel("Search commands").fill("telemetry");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/ops\/telemetry$/);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Telemetry History", exact: true })).toBeVisible();
});

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
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".command-palette-backdrop")).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await toggle.click();
  await expect(dialog).toHaveCSS("animation-name", "none");
  await expect(dialog.locator(".command-palette-surface")).toHaveCSS("animation-name", "none");
  await page.getByLabel("Search commands").fill("telemetry");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/ops\/telemetry$/);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Telemetry History", exact: true })).toBeVisible();
});

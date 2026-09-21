import { expect, test } from "@playwright/test";
import path from "node:path";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

for (const width of [1440, 768, 390]) {
  test(`workspace layout and keyboard navigation at ${width}px`, async ({ page }) => {
    const screenshotDirectory = process.env.UI_SCREENSHOT_DIR;
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installSessionMocks(page, createDefaultSessionState());
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "NANFO Access" })).toBeVisible();
    if (screenshotDirectory) await page.screenshot({ path: path.join(screenshotDirectory, `nanfo-ui-login-${width}.png`), fullPage: true });
    await loginFromUi(page);
    await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Network A", exact: true })).toBeVisible();
    await expect(page.locator(".network-choice").filter({ hasText: "Network A" })).toHaveAttribute("aria-pressed", "true");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (screenshotDirectory) await page.screenshot({ path: path.join(screenshotDirectory, `nanfo-ui-overview-${width}.png`), fullPage: true });
    await page.getByRole("link", { name: "Skip to workspace" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#workspace-content")).toBeFocused();
    await page.getByRole("button", { name: "Toggle command palette" }).click();
    await expect(page.getByLabel("Search commands")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Toggle command palette" })).toBeFocused();
    if (width <= 800) {
      const menu = page.getByRole("button", { name: "Toggle navigation" });
      await expect(menu).toHaveAttribute("aria-expanded", "false");
      await menu.click();
      await expect(menu).toHaveAttribute("aria-expanded", "true");
      await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Telemetry", exact: true }).focus();
      await page.keyboard.press("Escape");
      await expect(menu).toBeFocused();
      await expect(menu).toHaveAttribute("aria-expanded", "false");
      await menu.click();
      if (screenshotDirectory) await page.screenshot({ path: path.join(screenshotDirectory, `nanfo-ui-navigation-${width}.png`) });
    }
    const reports = page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Reports", exact: true });
    await reports.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/ops\/reports$/);
    if (width <= 800) {
      await expect(page.getByRole("button", { name: "Toggle navigation" })).toHaveAttribute("aria-expanded", "false");
      await expect(page.locator("#workspace-content")).toBeFocused();
    }
    await expect(page.getByRole("region", { name: "Report Generator", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (screenshotDirectory) await page.screenshot({ path: path.join(screenshotDirectory, `nanfo-ui-reports-${width}.png`), fullPage: true });
  });
}

for (const width of [1440, 390]) test(`all workspaces retain a readable hierarchy at ${width}px`, async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  await loginFromUi(page);
  await expect(page.locator(".network-choice").filter({ hasText: "Network A" })).toHaveAttribute("aria-pressed", "true");
  await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width, height: 1000 });
    for (const [route, title] of [["topology-analysis", "Topology"], ["telemetry", "Telemetry"], ["reliability", "Reliability"], ["digital-twin", "Digital Twin"], ["simulation", "Simulation"], ["intent", "Intent"], ["tenancy", "Tenancy"], ["plugins", "Plugins"], ["reports", "Reports"], ["audit", "Audit"], ["autonomy", "Governed Autonomy"]]) {
      if (width <= 800) await page.getByRole("button", { name: "Toggle navigation" }).click();
      await page.locator(`#main-navigation a[href="/ops/${route}"]`).click();
      await expect(page.getByRole("heading", { name: title, exact: true, level: 1 })).toBeVisible();
      await expect(page.locator(".panel, .autonomy-stop").first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${route} overflows at ${width}px`).toBe(true);
      if (process.env.UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.UI_SCREENSHOT_DIR, `nanfo-ui-${route}-${width}.png`), fullPage: true });
    }
});

import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test.describe("ADR019 metadata registry browser contracts", () => {
  test("register -> registry enable/disable -> confirmed authorized uninstall", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);
    await loginFromUi(page);
    await page.getByRole("link", { name: "Plugins" }).click();
    await expect(page.getByRole("heading", { name: "Plugin Metadata Registry" })).toBeVisible();
    await page.getByLabel("Plugin Key").fill("fixture-plugin");
    await page.getByLabel("Name", { exact: true }).fill("Fixture Plugin");
    await page.getByLabel("Signer").fill("nanfo-labs");
    await page.getByLabel("Signature", { exact: true }).fill("sig:fixture-declaration-only");
    await page.getByRole("button", { name: "Register Metadata" }).click();
    const card = page.locator("article").filter({ hasText: "Fixture Plugin" });
    await expect(card).toContainText("signature declared_unverified");
    await expect(card).toContainText("sandbox not_executed");
    await card.getByRole("button", { name: "Enable", exact: true }).click();
    await expect(card).toContainText("registry enabled");
    await card.getByRole("button", { name: "Disable", exact: true }).click();
    await expect(card).toContainText("registry disabled");
    let deleted = false;
    await page.route("**/api/v1/plugins/*", async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      expect(route.request().headers().authorization).toBe("Bearer token-1");
      deleted = true; state.plugins = [];
      await route.fulfill({ status: 204 });
    });
    await card.getByRole("button", { name: "Uninstall", exact: true }).click();
    expect(deleted).toBe(false);
    await card.getByRole("button", { name: "Cancel" }).click();
    expect(deleted).toBe(false);
    await card.getByRole("button", { name: "Uninstall", exact: true }).click();
    await card.getByRole("button", { name: "Confirm Uninstall" }).click();
    await expect(page.getByText("No plugins in registry")).toBeVisible();
    expect(deleted).toBe(true);
  });

  test("mobile declaration rejection and uninstall denial never claim runtime safety", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);
    await loginFromUi(page);
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("link", { name: "Plugins" }).click();
    await page.getByLabel("Plugin Key").fill("fixture-plugin");
    await page.getByLabel("Name", { exact: true }).fill("Fixture Plugin");
    await page.getByLabel("Signer").fill("unknown-signer");
    await page.getByLabel("Signature", { exact: true }).fill("sig:fixture-declaration-only");
    await page.getByRole("button", { name: "Register Metadata" }).click();
    await expect(page.getByText("Registry action failed")).toBeVisible();
    await page.getByLabel("Signer").fill("nanfo-labs");
    await page.getByRole("button", { name: "Register Metadata" }).click();
    await page.route("**/api/v1/plugins/*", async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      await route.fulfill({ status: 403, json: { success: false, data: null, meta: {}, errors: { code: "DENIED", message: "Permission revoked" } } });
    });
    const card = page.locator("article").filter({ hasText: "Fixture Plugin" });
    await card.getByRole("button", { name: "Uninstall", exact: true }).click();
    await card.getByRole("button", { name: "Confirm Uninstall" }).click();
    await expect(page.getByText("Permission revoked")).toBeVisible();
    await expect(card).toBeVisible();
    await expect(page.getByText("Registry entry uninstalled", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});

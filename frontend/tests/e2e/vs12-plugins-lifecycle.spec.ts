import { expect, test } from "@playwright/test";

import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS12 plugins lifecycle", () => {
  test("install -> enable -> disable success flow", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await loginFromUi(page);
    await page.getByRole("link", { name: "Plugins" }).click();
    await expect(page).toHaveURL(/\/ops\/plugins$/);
    await expect(page.getByRole("heading", { name: "Plugin Runtime Safety" })).toBeVisible();

    await page.getByLabel("Plugin Key").fill("safe-plugin");
    await page.getByLabel("Name").fill("Safe Plugin");
    await page.getByLabel("Version").fill("1.0.0");
    await page.getByLabel("Signer").fill("nanfo-labs");
    await page.getByLabel("Signature").fill("sig:abcdef1234567890");
    await page.getByLabel("Dependencies (comma-separated)").fill("core:telemetry");
    await page.getByLabel("Sandbox permissions").fill("read:telemetry, read:topology");
    await page.getByRole("button", { name: "Install Plugin" }).click();

    await expect(page.getByText("Plugin installed")).toBeVisible();
    const safeCard = page.locator("article").filter({ hasText: "Safe Plugin" });
    await expect(safeCard).toBeVisible();

    await safeCard.getByRole("button", { name: "Enable" }).click();
    await expect(page.getByText("Plugin enabled")).toBeVisible();
    await expect(safeCard).toContainText("enabled");

    await safeCard.getByRole("button", { name: "Disable" }).click();
    await expect(page.getByText("Plugin disabled")).toBeVisible();
    await expect(safeCard).toContainText("disabled");
  });

  test("install failure and safety-gate failure paths", async ({ page }) => {
    const state = createDefaultSessionState();
    state.plugins = [
      {
        plugin_id: "00000000-0000-0000-0000-000000000932",
        plugin_key: "unsafe-dependency-plugin",
        name: "Unsafe Dependency Plugin",
        version: "2.0.0",
        manifest: {
          plugin_key: "unsafe-dependency-plugin",
          name: "Unsafe Dependency Plugin",
          version: "2.0.0",
          signer: "nanfo-labs",
          signature: "sig:abcdef1234567890",
          dependencies: {
            platform_version: "9.9.9",
            requires: ["legacy:core"],
          },
          sandbox: {
            isolation_mode: "process",
            permissions: ["read:telemetry"],
          },
          metadata: {},
        },
        signature_status: "verified",
        dependency_status: "compatible",
        sandbox_status: "isolated",
        status: "installed",
        enabled: false,
        failure_reason: null,
        queue_status: "queued",
        stream_entry_id: "plugin-seed-932",
        warning: null,
        installed_at: "2026-08-14T12:10:00Z",
        updated_at: "2026-08-14T12:10:00Z",
      },
    ];

    await installSessionMocks(page, state);

    await loginFromUi(page);
    await page.getByRole("link", { name: "Plugins" }).click();

    await page.getByLabel("Plugin Key").fill("bad-signer-plugin");
    await page.getByLabel("Name").fill("Bad Signer Plugin");
    await page.getByLabel("Version").fill("1.0.0");
    await page.getByLabel("Signer").fill("unknown-signer");
    await page.getByLabel("Signature").fill("sig:abcdef1234567890");
    await page.getByRole("button", { name: "Install Plugin" }).click();

    await expect(page.getByText("Install failed")).toBeVisible();
    await expect(page.getByText("Plugin signer is not trusted.")).toBeVisible();

    const unsafeCard = page.locator("article").filter({ hasText: "Unsafe Dependency Plugin" });
    await expect(unsafeCard).toBeVisible();
    await unsafeCard.getByRole("button", { name: "Enable" }).click();

    await expect(page.getByText("Plugin blocked by safety checks")).toBeVisible();
    await expect(page.getByText("Plugin dependency requirements are incompatible with this runtime.")).toBeVisible();
    await expect(unsafeCard).toContainText("Failure reason: PLUGIN_DEPENDENCY_INCOMPATIBLE");
  });
});

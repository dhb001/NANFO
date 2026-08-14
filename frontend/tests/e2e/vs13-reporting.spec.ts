import { expect, test } from "@playwright/test";

import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS13 reporting lifecycle", () => {
  test("request -> terminal generated with artifact metadata", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await loginFromUi(page);
    await page.getByRole("link", { name: "Reports" }).click();
    await expect(page).toHaveURL(/\/ops\/reports$/);

    await page.getByRole("button", { name: "Generate Report" }).click();
    await expect(page.getByRole("button", { name: "Report request accepted" }).first()).toBeVisible();

    await expect(page.getByText("status generated")).toBeVisible();
    await expect(page.getByText("application/pdf")).toBeVisible();
    await expect(page.getByText(/s3:\/\/nanfo-reports\//)).toBeVisible();
  });

  test("failed report shows retry action and can recover", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await loginFromUi(page);
    await page.getByRole("link", { name: "Reports" }).click();

    await page.getByLabel("Filters JSON").fill('{"force_fail":true}');
    await page.getByRole("button", { name: "Generate Report" }).click();

    await expect(page.getByText("Report generation failed", { exact: true })).toBeVisible();
    await expect(page.getByText("Report generation failed during queue processing.")).toBeVisible();

    await page.getByLabel("Filters JSON").fill('{"kpi":"latency"}');
    await page.getByRole("button", { name: "Retry Failed Report" }).click();

    await expect(page.getByRole("button", { name: "Report request accepted" }).first()).toBeVisible();
    await expect(page.getByText("status generated")).toBeVisible();
  });
});

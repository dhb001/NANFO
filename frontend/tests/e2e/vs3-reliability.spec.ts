import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS3 reliability", () => {
  test("reliability dashboard renders health and filter controls", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/telemetry/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            status: "degraded",
            ingest_lag_ms: 1450,
            dropped_events: 12,
            latest_observed_at: "2026-08-13T10:40:00Z",
            total_records: 3250,
          },
          meta: { request_id: "req-rel-health", timestamp: "2026-08-13T10:40:00Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Reliability" }).click();
    await expect(page).toHaveURL(/\/ops\/reliability$/);

    await expect(page.getByText("Runtime Reliability")).toBeVisible();
    await expect(page.getByText("Collector Status")).toBeVisible();
    await expect(page.getByText("DEGRADED")).toBeVisible();

    await page.getByLabel("Filter alerts").fill("critical");
    await page.getByRole("button", { name: "Active" }).click();
    await expect(page.getByText("No reliability alerts observed yet.")).toBeVisible();
  });
});

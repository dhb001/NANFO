import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS11 alerts lifecycle", () => {
  test("list -> acknowledge -> resolve with status filtering", async ({ page }) => {
    const state = createDefaultSessionState();
    state.alerts = [
      {
        alert_id: "00000000-0000-0000-0000-00000000aa01",
        alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
        source: "telemetry",
        status: "active",
        severity: "critical",
        correlation_id: "00000000-0000-0000-0000-00000000bb01",
        payload: {
          alert_id: "00000000-0000-0000-0000-00000000aa01",
          alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
          status: "active",
          severity: "critical",
          severity_reason: "invalid_sample_ratio_exceeded",
          runbook_reference: "docs/project/TelemetryRuntimeAdapterRunbook.md",
        },
        acknowledged_by_user_id: null,
        resolved_by_user_id: null,
        acknowledged_at: null,
        resolved_at: null,
        created_at: "2026-08-14T11:50:00Z",
        updated_at: "2026-08-14T11:55:00Z",
      },
    ];

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
            latest_observed_at: "2026-08-14T12:00:00Z",
            total_records: 3250,
          },
          meta: { request_id: "req-rel-health", timestamp: "2026-08-14T12:00:00Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Reliability" }).click();
    await expect(page).toHaveURL(/\/ops\/reliability$/);
    await expect(page.getByRole("heading", { name: "Alerts Lifecycle" })).toBeVisible();
    const alertCard = page.locator("article").filter({
      hasText: "telemetry_runtime_adapter_slo_threshold_breach",
    });
    await expect(alertCard).toBeVisible();
    await expect(alertCard).toContainText("active");

    await page.getByRole("button", { name: "Acknowledge" }).click();
    await expect(alertCard).toContainText("acknowledged");

    await page.getByRole("button", { name: "Ack", exact: true }).click();
    await expect(alertCard).toBeVisible();

    await page.getByRole("button", { name: "Resolve", exact: true }).click();
    await page.getByRole("button", { name: "Resolved", exact: true }).click();
    await expect(alertCard).toBeVisible();
    await expect(alertCard).toContainText("resolved");

    await page.getByLabel("Filter alerts").fill("threshold");
    await expect(alertCard).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS3 reliability", () => {
  test("reliability dashboard renders health and filter controls", async ({ page }) => {
    const state = createDefaultSessionState();
    state.alerts = [
      {
        alert_id: "00000000-0000-0000-0000-00000000cc01",
        alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
        source: "telemetry",
        status: "active",
        severity: "critical",
        correlation_id: "00000000-0000-0000-0000-00000000dd01",
        payload: {
          alert_id: "00000000-0000-0000-0000-00000000cc01",
          alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
          status: "active",
          severity: "critical",
          severity_reason: "ingest_failures_detected",
        },
        acknowledged_by_user_id: null,
        resolved_by_user_id: null,
        acknowledged_at: null,
        resolved_at: null,
        created_at: "2026-08-13T10:30:00Z",
        updated_at: "2026-08-13T10:35:00Z",
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

    await page.getByLabel("Filter alerts").fill("threshold");
    await page.getByRole("button", { name: "Active" }).click();
    await expect(page.getByText("telemetry_runtime_adapter_slo_threshold_breach")).toBeVisible();
    await expect(page.getByRole("button", { name: "Acknowledge" })).toBeVisible();
  });
});

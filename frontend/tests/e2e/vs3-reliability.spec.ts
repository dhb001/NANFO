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

  test("reliability dashboard remains usable under high alert volume fixtures", async ({ page }) => {
    const state = createDefaultSessionState();
    state.alerts = Array.from({ length: 180 }, (_, index) => {
      const serial = String(index + 1).padStart(12, "0");
      const status = index % 3 === 0 ? "active" : index % 3 === 1 ? "acknowledged" : "resolved";
      return {
        alert_id: `00000000-0000-0000-0000-${serial}`,
        alert_key: `telemetry_runtime_adapter_alert_${index}`,
        source: "telemetry",
        status,
        severity: index % 5 === 0 ? "critical" : "high",
        correlation_id: `00000000-0000-0000-0000-${String(index + 6000).padStart(12, "0")}`,
        payload: {
          alert_id: `00000000-0000-0000-0000-${serial}`,
          alert_key: `telemetry_runtime_adapter_alert_${index}`,
          status,
          severity: index % 5 === 0 ? "critical" : "high",
          severity_reason: "synthetic_burst",
        },
        acknowledged_by_user_id: status === "acknowledged" ? state.userId : null,
        resolved_by_user_id: status === "resolved" ? state.userId : null,
        acknowledged_at: status === "acknowledged" ? "2026-08-14T12:00:00Z" : null,
        resolved_at: status === "resolved" ? "2026-08-14T12:01:00Z" : null,
        created_at: "2026-08-14T11:30:00Z",
        updated_at: "2026-08-14T12:05:00Z",
      };
    });
    await installSessionMocks(page, state);

    await page.route("**/api/v1/telemetry/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            status: "degraded",
            ingest_lag_ms: 1700,
            dropped_events: 18,
            latest_observed_at: "2026-08-14T12:05:00Z",
            total_records: 5600,
          },
          meta: { request_id: "req-rel-high-volume", timestamp: "2026-08-14T12:05:00Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Reliability" }).click();
    await expect(page).toHaveURL(/\/ops\/reliability$/);
    await expect(page.getByText("Runtime Reliability")).toBeVisible();

    await page.getByLabel("Filter alerts").fill("telemetry_runtime_adapter_alert_17");
    await expect(page.getByText("telemetry_runtime_adapter_alert_17", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Resolved" }).click();
    const resolvedCard = page.locator("article").filter({
      has: page.getByText("telemetry_runtime_adapter_alert_170", { exact: true }),
    });
    await expect(resolvedCard).toBeVisible();
    await expect(resolvedCard.getByRole("button", { name: "Acknowledge" })).toBeDisabled();
    await expect(resolvedCard.getByRole("button", { name: "Resolve" })).toBeDisabled();

    await page.getByRole("button", { name: "Active" }).click();
    const activeCard = page.locator("article").filter({
      has: page.getByText("telemetry_runtime_adapter_alert_171", { exact: true }),
    });
    await expect(activeCard).toBeVisible();
    await expect(activeCard.getByRole("button", { name: "Acknowledge" })).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  type SessionMockState,
  loginFromUi,
} from "./support/session";

function createHighVolumeState(): SessionMockState {
  const state = createDefaultSessionState();

  state.alerts = Array.from({ length: 240 }, (_, index) => {
    const serial = String(index + 1).padStart(12, "0");
    const status = index % 3 === 0 ? "active" : index % 3 === 1 ? "acknowledged" : "resolved";
    return {
      alert_id: `00000000-0000-0000-0000-${serial}`,
      alert_key: `vs19_alert_${index}`,
      source: "telemetry",
      status,
      severity: index % 5 === 0 ? "critical" : "high",
      correlation_id: `00000000-0000-0000-0000-${String(index + 5000).padStart(12, "0")}`,
      payload: {
        alert_id: `00000000-0000-0000-0000-${serial}`,
        alert_key: `vs19_alert_${index}`,
        status,
        severity: index % 5 === 0 ? "critical" : "high",
      },
      acknowledged_by_user_id: status === "acknowledged" ? state.userId : null,
      resolved_by_user_id: status === "resolved" ? state.userId : null,
      acknowledged_at: status === "acknowledged" ? "2026-08-15T20:00:00Z" : null,
      resolved_at: status === "resolved" ? "2026-08-15T20:01:00Z" : null,
      created_at: "2026-08-15T19:55:00Z",
      updated_at: "2026-08-15T20:02:00Z",
    };
  });

  return state;
}

test.describe("VS19 frontend continuity", () => {
  test("telemetry and reliability remain responsive under elevated fixture volumes", async ({ page }) => {
    const state = createHighVolumeState();
    await installSessionMocks(page, state);

    const telemetryHistoryItems = Array.from({ length: 220 }, (_, index) => {
      return {
        record_id: `telemetry-record-${index}`,
        event_id: `telemetry-event-${index}`,
        correlation_id: `telemetry-corr-${index}`,
        device_id: `00000000-0000-0000-0000-${String(index + 1000).padStart(12, "0")}`,
        network_id: "00000000-0000-0000-0000-000000000333",
        workspace_id: "00000000-0000-0000-0000-000000000222",
        metric: index % 2 === 0 ? "cpu_usage" : "packet_loss",
        value: index % 2 === 0 ? 40 + (index % 20) : (index % 10) / 10,
        unit: index % 2 === 0 ? "%" : "%",
        observed_at: `2026-08-15T20:${String(index % 60).padStart(2, "0")}:00Z`,
        source: "runtime",
        tags: {
          lane: index % 4,
          scenario: "vs19",
        },
        created_at: `2026-08-15T20:${String(index % 60).padStart(2, "0")}:00Z`,
      };
    });

    await page.route("**/api/v1/telemetry/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            status: "degraded",
            ingest_lag_ms: 980,
            dropped_events: 0,
            latest_observed_at: "2026-08-15T20:05:00Z",
            total_records: 12580,
          },
          meta: { request_id: "req-vs19-health", timestamp: "2026-08-15T20:05:00Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/telemetry/history**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            items: telemetryHistoryItems,
            total: telemetryHistoryItems.length,
            page: 1,
            page_size: 120,
          },
          meta: { request_id: "req-vs19-history", timestamp: "2026-08-15T20:05:01Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/telemetry/device/**", async (route) => {
      const topRows = telemetryHistoryItems.slice(0, 100);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device_id: topRows[0]?.device_id ?? "00000000-0000-0000-0000-000000000000",
            items: topRows,
            total: topRows.length,
            page: 1,
            page_size: 100,
          },
          meta: { request_id: "req-vs19-device-history", timestamp: "2026-08-15T20:05:02Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Telemetry" }).click();
    await expect(page).toHaveURL(/\/ops\/telemetry$/);
    await expect(page.getByRole("heading", { name: "Telemetry History" })).toBeVisible();
    await page.getByLabel("Filter telemetry metric").fill("packet_loss");
    const firstHistoryButton = page.getByRole("region", { name: "Telemetry History", exact: true }).getByRole("button", { name: /packet_loss/ }).first();
    await expect(firstHistoryButton).toBeVisible();
    await firstHistoryButton.click();
    await expect(page.getByText("Device Drilldown")).toBeVisible();

    await page.getByRole("link", { name: "Reliability" }).click();
    await expect(page).toHaveURL(/\/ops\/reliability$/);
    const alertFilterInput = page.getByLabel("Filter alerts");
    await alertFilterInput.fill("vs19_alert_199");
    await expect(page.getByText("vs19_alert_199", { exact: true })).toBeVisible();
    await alertFilterInput.fill("");

    await page.getByRole("button", { name: "Resolved" }).click();
    await expect(page.getByText("vs19_alert_197", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Active" }).click();
    await expect(page.getByText("vs19_alert_198", { exact: true })).toBeVisible();
  });
});

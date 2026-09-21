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

  test("mobile measured history shows thresholds, provenance and correlated recovery", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const state = createDefaultSessionState();
    const id = "00000000-0000-0000-0000-00000000aa02";
    const payload = { alert_id: id, rule: { version: "operator-v1", breach: 100, recover: 70, duration_seconds: 10, min_samples: 3, max_gap_seconds: 10, max_age_seconds: 30 },
      metric: "latency_ms", value: 120, unit: "ms", observed_at: "2026-09-11T00:00:10Z", window_started_at: "2026-09-11T00:00:00Z", sample_count: 3,
      source: "emulation", execution_mode: "emulation", quality: "measured", synthetic: false, measurement_method: "ping_rtt", observation_event_id: "00000000-0000-0000-0000-000000000001",
      org_id: state.orgId, workspace_id: state.workspaceId, network_id: state.networks[0].network_id, device_id: "00000000-0000-0000-0000-000000000444", port_no: null, peer_host: "h2", run_id: "00000000-0000-0000-0000-000000000555", rule_version: "operator-v1" };
    state.alerts = [{ alert_id: id, alert_key: "measured:fixture", source: "telemetry", status: "resolved", severity: "warning", correlation_id: "00000000-0000-0000-0000-000000000111", payload: { ...payload, value: 60, resolution_reason: "measured_recovery" },
      acknowledged_by_user_id: null, resolved_by_user_id: null, acknowledged_at: null, resolved_at: "2026-09-11T00:01:10Z", created_at: "2026-09-11T00:00:10Z", updated_at: "2026-09-11T00:01:10Z" }];
    await installSessionMocks(page, state);
    let denied = false;
    await page.route(`**/api/v1/alerts/${id}**`, async (route) => {
      expect(route.request().headers().authorization).toBe("Bearer token-1");
      if (denied) return route.fulfill({ status: 403, json: { success: false, data: null, meta: {}, errors: { code: "DENIED", message: "History permission revoked" } } });
      const history = route.request().url().endsWith("/history");
      await route.fulfill({ json: { success: true, data: history ? { alert_id: id, total: 2, items: [
        { event_id: "00000000-0000-0000-0000-000000000001", alert_id: id, event_type: "alert.generated", correlation_id: state.alerts[0].correlation_id, occurred_at: "2026-09-11T00:00:10Z", payload },
        { event_id: "00000000-0000-0000-0000-000000000002", alert_id: id, event_type: "alert.resolved", correlation_id: state.alerts[0].correlation_id, occurred_at: "2026-09-11T00:01:10Z", payload: state.alerts[0].payload },
      ] } : state.alerts[0], meta: {}, errors: null } });
    });
    await loginFromUi(page);
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("link", { name: "Reliability" }).click();
    const expand = page.getByRole("button", { name: "Details and History" });
    await expand.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Immutable Lifecycle History" })).toBeVisible();
    await expect(page.getByText(/breach >= 100 ms; recovery < 70 ms/).first()).toBeVisible();
    await expect(page.getByText(/synthetic false; method ping_rtt/).first()).toBeVisible();
    await expect(page.getByText("Resolution reason: measured_recovery").first()).toBeVisible();
    denied = true;
    await page.getByRole("button", { name: "Refresh Alert History" }).click();
    await expect(page.getByText("History permission revoked").first()).toBeVisible();
    await expect(page.getByText("alert.generated", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});

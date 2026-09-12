import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS2 telemetry and topology", () => {
  test("telemetry dashboard and digital twin inspector flow", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/telemetry/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            status: "ok",
            ingest_lag_ms: 320,
            dropped_events: 1,
            latest_observed_at: "2026-08-13T10:30:00Z",
            total_records: 1220,
          },
          meta: { request_id: "req-t-health", timestamp: "2026-08-13T10:30:00Z" },
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
            items: [
              {
                record_id: "record-1",
                event_id: "event-1",
                correlation_id: "corr-1",
                device_id: "00000000-0000-0000-0000-000000000444",
                network_id: "00000000-0000-0000-0000-000000000333",
                workspace_id: "00000000-0000-0000-0000-000000000222",
                metric: "cpu_usage",
                value: 64.2,
                unit: "%",
                observed_at: "2026-08-13T10:29:59Z",
                source: "runtime",
                tags: {},
                created_at: "2026-08-13T10:29:59Z",
              },
            ],
            total: 1,
            page: 1,
            page_size: 120,
          },
          meta: { request_id: "req-t-history", timestamp: "2026-08-13T10:30:01Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/telemetry/device/00000000-0000-0000-0000-000000000444**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device_id: "00000000-0000-0000-0000-000000000444",
            items: [
              {
                record_id: "record-1",
                event_id: "event-1",
                correlation_id: "corr-1",
                device_id: "00000000-0000-0000-0000-000000000444",
                network_id: "00000000-0000-0000-0000-000000000333",
                workspace_id: "00000000-0000-0000-0000-000000000222",
                metric: "cpu_usage",
                value: 64.2,
                unit: "%",
                observed_at: "2026-08-13T10:29:59Z",
                source: "runtime",
                tags: {},
                created_at: "2026-08-13T10:29:59Z",
              },
            ],
            total: 1,
            page: 1,
            page_size: 100,
          },
          meta: { request_id: "req-t-device", timestamp: "2026-08-13T10:30:01Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/graph?network_id=00000000-0000-0000-0000-000000000333&limit=200", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            nodes: [
              {
                device_id: "00000000-0000-0000-0000-000000000444",
                hostname: "edge-1",
                device_type: "switch",
                status: "active",
                spatial_ref_id: "campus-a/building-1/floor-1/rack-2",
              },
              {
                device_id: "00000000-0000-0000-0000-000000000445",
                hostname: "core-1",
                device_type: "router",
                status: "active",
                spatial_ref_id: "campus-a/building-1/floor-1/rack-1",
              },
            ],
            edges: [
              {
                source_id: "00000000-0000-0000-0000-000000000445",
                target_id: "00000000-0000-0000-0000-000000000444",
                edge_type: "connected_to",
                metadata: {},
              },
            ],
          },
          meta: {
            request_id: "req-topology-graph",
            timestamp: "2026-08-13T10:30:02Z",
            execution_time_ms: 2,
            next_cursor: null,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/nodes/00000000-0000-0000-0000-000000000444?depth=1", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            node: {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/building-1/floor-1/rack-2",
            },
            neighbours: [
              {
                device_id: "00000000-0000-0000-0000-000000000445",
                hostname: "core-1",
                device_type: "router",
                status: "active",
                spatial_ref_id: "campus-a/building-1/floor-1/rack-1",
                edge_type: "connected_to",
                direction: "inbound",
              },
            ],
          },
          meta: { request_id: "req-topology-node", timestamp: "2026-08-13T10:30:03Z", execution_time_ms: 2 },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Telemetry" }).click();
    await expect(page).toHaveURL(/\/ops\/telemetry$/);
    await expect(page.getByText("Telemetry Health")).toBeVisible();
    await expect(page.getByRole("region", { name: "Telemetry Health", exact: true }).getByText(/1,?220/)).toBeVisible();
    await expect(page.getByRole("region", { name: "Telemetry History", exact: true }).getByRole("button", { name: /cpu_usage/ })).toBeVisible();

    await page.getByRole("link", { name: "Digital Twin" }).click();
    await expect(page).toHaveURL(/\/ops\/digital-twin$/);
    await page.getByLabel("Inspect node").selectOption("00000000-0000-0000-0000-000000000444");

    const inspectorPanel = page.locator("section").filter({ has: page.getByRole("heading", { name: "Inspector" }) });
    await expect(inspectorPanel.locator("strong", { hasText: "edge-1" })).toBeVisible();
    await expect(inspectorPanel.locator("span", { hasText: "core-1" })).toBeVisible();
  });
});

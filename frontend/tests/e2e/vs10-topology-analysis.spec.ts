import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS10 topology analysis", () => {
  test("renders neighbours and impact and runs reconcile", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

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
                spatial_ref_id: "campus-a/edge-1",
              },
            ],
            edges: [],
          },
          meta: {
            request_id: "req-vs10-graph",
            timestamp: "2026-08-14T12:00:00Z",
            execution_time_ms: 2,
            next_cursor: null,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/device/00000000-0000-0000-0000-000000000444/neighbors?depth=2&limit=200", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device: {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/edge-1",
            },
            neighbours: [
              {
                device_id: "00000000-0000-0000-0000-000000000445",
                hostname: "core-1",
                device_type: "router",
                status: "active",
                spatial_ref_id: "campus-a/core-1",
                edge_type: "connected_to",
                edge_metadata: { link_quality: "good" },
                direction: "inbound",
                hop_depth: 1,
              },
            ],
            depth: 2,
            total: 1,
          },
          meta: {
            request_id: "req-vs10-neighbours",
            timestamp: "2026-08-14T12:00:01Z",
            execution_time_ms: 3,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/impact/00000000-0000-0000-0000-000000000444?max_hops=3&limit=500", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device: {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: "campus-a/edge-1",
            },
            impacts: [
              {
                device_id: "00000000-0000-0000-0000-000000000446",
                hostname: "dist-1",
                device_type: "switch",
                status: "active",
                spatial_ref_id: null,
                hop_depth: 2,
              },
            ],
            max_hops: 3,
            total: 1,
          },
          meta: {
            request_id: "req-vs10-impact",
            timestamp: "2026-08-14T12:00:02Z",
            execution_time_ms: 4,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/reconcile", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            reconcile_id: "reconcile-1",
            network_id: "00000000-0000-0000-0000-000000000333",
            status: "completed",
            checked_nodes: 7,
            checked_edges: 6,
            missing_workspace_nodes: 1,
            workspace_backfilled_nodes: 1,
            warning: null,
          },
          meta: {
            request_id: "req-vs10-reconcile",
            timestamp: "2026-08-14T12:00:03Z",
            execution_time_ms: 6,
          },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);
    await expect(page.getByRole("heading", { name: "Networks" })).toBeVisible();
    await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
    await page.getByRole("link", { name: "Topology" }).click();
    await expect(page).toHaveURL(/\/ops\/topology-analysis$/);

    await expect(page.getByText("Neighbour Analysis")).toBeVisible();
    await expect(page.getByText("core-1")).toBeVisible();
    await expect(page.getByText("hop 1: 1")).toBeVisible();

    await page.getByRole("button", { name: "Impact" }).click();
    await expect(page.getByText("Impact Analysis")).toBeVisible();
    await expect(page.getByText("dist-1")).toBeVisible();

    await page.getByRole("button", { name: "Run Reconcile" }).click();
    await expect(page.getByText("reconcile_id: reconcile-1")).toBeVisible();
  });

  test("shows empty states for no neighbours and no impacts", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

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
                spatial_ref_id: null,
              },
            ],
            edges: [],
          },
          meta: {
            request_id: "req-vs10-graph-empty",
            timestamp: "2026-08-14T12:10:00Z",
            execution_time_ms: 2,
            next_cursor: null,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/device/00000000-0000-0000-0000-000000000444/neighbors?depth=2&limit=200", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device: {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: null,
            },
            neighbours: [],
            depth: 2,
            total: 0,
          },
          meta: {
            request_id: "req-vs10-neighbours-empty",
            timestamp: "2026-08-14T12:10:01Z",
            execution_time_ms: 3,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/topology/impact/00000000-0000-0000-0000-000000000444?max_hops=3&limit=500", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device: {
              device_id: "00000000-0000-0000-0000-000000000444",
              hostname: "edge-1",
              device_type: "switch",
              status: "active",
              spatial_ref_id: null,
            },
            impacts: [],
            max_hops: 3,
            total: 0,
          },
          meta: {
            request_id: "req-vs10-impact-empty",
            timestamp: "2026-08-14T12:10:02Z",
            execution_time_ms: 4,
          },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);
    await expect(page.getByRole("heading", { name: "Networks" })).toBeVisible();
    await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
    await page.getByRole("link", { name: "Topology" }).click();

    await expect(page.getByText("No neighbours reachable")).toBeVisible();
    await page.getByRole("button", { name: "Impact" }).click();
    await expect(page.getByText("No impacted dependencies")).toBeVisible();
  });
});

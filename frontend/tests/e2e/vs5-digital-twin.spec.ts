import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS5 digital twin realtime resilience", () => {
  test("renders topology scene and tolerates websocket unavailability", async ({ page }) => {
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
                spatial_ref_id: "campus-a/building-1/floor-1/rack-2",
              },
            ],
            edges: [],
          },
          meta: {
            request_id: "req-vs5-graph",
            timestamp: "2026-08-13T10:50:00Z",
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
            neighbours: [],
          },
          meta: { request_id: "req-vs5-node", timestamp: "2026-08-13T10:50:01Z", execution_time_ms: 2 },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Digital Twin" }).click();
    await expect(page).toHaveURL(/\/ops\/digital-twin$/);
    await expect(page.getByText("3D Digital Twin")).toBeVisible();
    await expect(page.getByText(/topology\s+(connecting|closed)/i)).toBeVisible();
    await expect(page.getByText(/digital twin\s+(connecting|closed)/i)).toBeVisible();
  });
});

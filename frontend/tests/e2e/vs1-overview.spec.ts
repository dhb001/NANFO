import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS1 overview flows", () => {
  test("auth + tenancy + network/device flows with spatial update", async ({ page }) => {
    const state = createDefaultSessionState();

    await installSessionMocks(page, state);

    await page.route("**/api/v1/networks/00000000-0000-0000-0000-000000000333/devices/00000000-0000-0000-0000-000000000444", async (route) => {
      expect(route.request().method()).toBe("PATCH");
      const body = route.request().postDataJSON() as { spatial_ref_id: string | null };
      expect(body.spatial_ref_id).toBe("campus-a/building-1/floor-3/rack-9");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            device_id: "00000000-0000-0000-0000-000000000444",
            network_id: "00000000-0000-0000-0000-000000000333",
            hostname: "edge-1",
            ip_address: null,
            device_type: "switch",
            vendor: null,
            model: null,
            location_hint: null,
            spatial_ref_id: "campus-a/building-1/floor-3/rack-9",
            status: "active",
            created_at: "2026-08-13T09:25:00Z",
          },
          meta: { request_id: "req-spatial-update", timestamp: "2026-08-13T10:20:00Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await expect(page.getByText("Workspace Capacity")).toBeVisible();
    await expect(page.getByText("edge-1")).toBeVisible();

    await page.getByLabel("Spatial reference for edge-1").fill("campus-a/building-1/floor-3/rack-9");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Spatial reference updated")).toBeVisible();
  });
});

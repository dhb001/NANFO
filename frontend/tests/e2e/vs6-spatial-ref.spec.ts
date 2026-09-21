import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS6 spatial references", () => {
  test("updates device spatial_ref_id from overview", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    let observedPatch: { spatial_ref_id: string | null } | null = null;

    await page.route("**/api/v1/networks/00000000-0000-0000-0000-000000000333/devices/00000000-0000-0000-0000-000000000444", async (route) => {
      observedPatch = route.request().postDataJSON() as { spatial_ref_id: string | null };

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
            spatial_ref_id: observedPatch?.spatial_ref_id,
            status: "active",
            created_at: "2026-08-13T09:25:00Z",
          },
          meta: { request_id: "req-vs6-update", timestamp: "2026-08-13T11:10:00Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("button", { name: "Edit edge-1" }).click();
    await page.getByRole("form", { name: "Edit device" }).getByLabel("Spatial reference").fill("campus-a/building-2/floor-1/rack-1");
    await page.getByRole("button", { name: "Save device" }).click();

    await expect(page.getByRole("form", { name: "Edit device" })).toHaveCount(0);
    expect(observedPatch).toEqual({ spatial_ref_id: "campus-a/building-2/floor-1/rack-1" });
  });
});

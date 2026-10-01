import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";
import { inspectNode } from "./support/twin";

test.describe("VS5 digital twin realtime resilience", () => {
  test("renders topology scene, congestion legend, and configure handoff", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/topology/graph?network_id=00000000-0000-0000-0000-000000000333&limit=500", async (route) => {
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
                spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
              },
            ],
            edges: [
              {
                source_id: "00000000-0000-0000-0000-000000000444",
                target_id: "00000000-0000-0000-0000-000000000444",
                edge_type: "connected_to",
                metadata: {},
              },
            ],
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
              spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
            },
            neighbours: [],
          },
          meta: { request_id: "req-vs5-node", timestamp: "2026-08-13T10:50:01Z", execution_time_ms: 2 },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);
    await expect(page.getByRole("heading", { name: "Networks" })).toBeVisible();
    await page.locator(".network-choice").filter({ hasText: "Network A" }).click();

    await page.getByRole("link", { name: "Digital Twin" }).click();
    await expect(page).toHaveURL(/\/ops\/digital-twin$/);
    await expect(page.getByText("3D Digital Twin")).toBeVisible();
    await expect(page.getByText(/topology\s+(open|connecting|closed)/i)).toBeVisible();
    await expect(page.getByText(/digital twin\s+(open|connecting|closed)/i)).toBeVisible();
    await expect(page.getByText("Congestion legend")).toBeVisible();
    // The invented congestion policy is gone (FE-Twin fix 2): backend alerts are authoritative.
    await expect(page.getByText("Authoritative severity: backend alerts.", { exact: false })).toBeVisible();

    await inspectNode(page, "00000000-0000-0000-0000-000000000444");
    await page.getByRole("button", { name: "Configure in Intent Workflow" }).click();
    await expect(page).toHaveURL(/\/ops\/intent(\?.*)?$/);
  });

  test("renders congestion controls and supports local import happy path", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    let persistedSpatialRefByDeviceId: Record<string, string | null> = {
      "00000000-0000-0000-0000-000000000444": null,
    };

    await page.route("**/api/v1/topology/graph?network_id=00000000-0000-0000-0000-000000000333&limit=500", async (route) => {
      const persistedSpatialRef = persistedSpatialRefByDeviceId["00000000-0000-0000-0000-000000000444"];
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
                spatial_ref_id: persistedSpatialRef,
              },
            ],
            edges: [],
          },
          meta: {
            request_id: "req-vs5-graph-2",
            timestamp: "2026-08-13T10:50:00Z",
            execution_time_ms: 2,
            next_cursor: null,
          },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/networks/00000000-0000-0000-0000-000000000333/devices/00000000-0000-0000-0000-000000000444", async (route) => {
      const requestBody = route.request().postDataJSON() as { spatial_ref_id?: string | null };
      persistedSpatialRefByDeviceId = {
        ...persistedSpatialRefByDeviceId,
        "00000000-0000-0000-0000-000000000444": requestBody.spatial_ref_id ?? null,
      };

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
            spatial_ref_id: requestBody.spatial_ref_id ?? null,
            status: "active",
            created_at: "2026-08-18T09:00:00Z",
          },
          meta: {
            request_id: "req-vs5-device-patch",
            timestamp: "2026-08-18T09:00:02Z",
            execution_time_ms: 4,
          },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);
    await expect(page.getByRole("heading", { name: "Networks" })).toBeVisible();
    await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
    await page.getByRole("link", { name: "Digital Twin" }).click();

    await page.getByRole("button", { name: "Congestion" }).click();
    await expect(page.getByRole("button", { name: "Congestion" })).toHaveAttribute("aria-pressed", "false");
    await page.getByRole("button", { name: "Congestion" }).click();
    await expect(page.getByRole("button", { name: "Congestion" })).toHaveAttribute("aria-pressed", "true");

    await page.getByLabel("Campus model file").setInputFiles({
      name: "campus.glb",
      mimeType: "model/gltf-binary",
      buffer: (() => {
        const json = JSON.stringify({ asset: { version: "2.0" }, scenes: [{ nodes: [0] }], nodes: [{ name: "campus" }], scene: 0 });
        const chunk = Buffer.from(json.padEnd(Math.ceil(json.length / 4) * 4, " "));
        const header = Buffer.alloc(20);
        [0x46546c67, 2, chunk.length + 20, chunk.length, 0x4e4f534a].forEach((value, index) => header.writeUInt32LE(value, index * 4));
        return Buffer.concat([header, chunk]);
      })(),
    });
    await expect(page.getByText(/model GLB/i)).toBeVisible();

    await page.getByLabel("Campus mapping file").setInputFiles({
      name: "mapping.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        JSON.stringify([
          {
            object_name: "rack-2",
            device_id: "00000000-0000-0000-0000-000000000444",
            spatial_ref_id: "campus-a/building-1/floor-1/rack-2/device-1",
          },
          {
            object_name: "rack-3",
            device_id: "missing-device-id",
            spatial_ref_id: "campus-a/building-1/floor-1/rack-3/device-2",
          },
          {
            object_name: "rack-3",
            device_id: "00000000-0000-0000-0000-000000000444",
            spatial_ref_id: "campus-a/building-1/floor-1/rack-4/device-3",
          },
        ]),
      ),
    });

    await expect(page.getByText("matched 1", { exact: true })).toBeVisible();
    await expect(page.getByText("unmatched 1", { exact: true })).toBeVisible();
    await expect(page.getByText("duplicates 1", { exact: true })).toBeVisible();

    await inspectNode(page, "00000000-0000-0000-0000-000000000444");
    await expect(page.getByRole("button", { name: "Persist Mapping to Device" })).toBeVisible();
    await page.getByRole("button", { name: "Persist Mapping to Device" }).click();
    await expect(page.getByRole("button", { name: "Persist Mapping to Device" })).toBeDisabled();
  });

  test("shows import validation error for invalid model file", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/topology/graph?network_id=00000000-0000-0000-0000-000000000333&limit=500", async (route) => {
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
            request_id: "req-vs5-graph-3",
            timestamp: "2026-08-13T10:50:00Z",
            execution_time_ms: 2,
            next_cursor: null,
          },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);
    await expect(page.getByRole("heading", { name: "Networks" })).toBeVisible();
    await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
    await page.getByRole("link", { name: "Digital Twin" }).click();

    await page.getByLabel("Campus model file").setInputFiles({
      name: "campus.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("invalid"),
    });
    await expect(page.getByText("Model file must be .glb or .gltf.")).toBeVisible();
  });
});

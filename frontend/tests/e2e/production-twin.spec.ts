import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";
import { inspectNode } from "./support/twin";

test("Twin renders canonical geometry and loads glTF through production-safe public UI", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installSessionMocks(page, createDefaultSessionState());
  const envelope = (data: unknown) => ({ success: true, data, meta: {}, errors: null });
  const device = "00000000-0000-0000-0000-000000000444";
  const node = { device_id: device, hostname: "catalogue-switch", device_type: "switch", status: "active", spatial_ref_id: null };
  await page.route("**/api/v1/topology/graph?**", (route) => route.fulfill({ json: envelope({ nodes: [node], edges: [] }) }));
  await page.route("**/api/v1/topology/nodes/**", (route) => route.fulfill({ json: envelope({ node, neighbours: [] }) }));
  const transform = { position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "browser-fixture", accuracy_m: null } };
  await page.route("**/spatial-scene", (route) => route.fulfill({ json: envelope({
    version: 1, revision: 3, coordinate_system: { units: "m", up_axis: "y" }, objects: [
      { ...transform, object_id: "floor", parent_id: null, object_type: "floor", name: "Fixture floor", device_id: null, geometry: { kind: "slab", width: 20, depth: 12, thickness: 0.2 } },
      { ...transform, object_id: "wall", parent_id: "floor", object_type: "wall", name: "Fixture wall", device_id: null, geometry: { kind: "wall", length: 8, height: 3, thickness: 0.2, material: { name: "brick", attenuation_db: null, source: "browser-fixture" } } },
      { ...transform, object_id: "switch", parent_id: "floor", object_type: "device", name: "Fixture switch", device_id: device },
    ],
  }) }));
  await page.routeWebSocket(/\/ws\//, (socket) => socket.onMessage((message) => {
    const request = JSON.parse(String(message));
    socket.send(JSON.stringify({ event: "subscribed", channel: request.channel, filters: request.filters }));
  }));
  await loginFromUi(page);
  await page.getByRole("button", { name: /Network A/, pressed: true }).click();
  await page.getByRole("link", { name: "Digital Twin", exact: true }).click();
  await expect(page.locator("canvas")).toBeVisible();
  // Scene labels render in one shared layer (FE-Twin fix 3); canonical labels use the geometry variant.
  const wallLabel = page.locator(".twin-label--geometry", { hasText: "Fixture wall" });
  await expect(wallLabel).toContainText("brick");
  await page.getByLabel("Canonical floor", { exact: true }).selectOption("floor");
  await page.getByLabel("Clip above floor (m)", { exact: true }).fill("2");
  await expect(wallLabel).toHaveCount(0);
  await page.getByLabel("Canonical floor", { exact: true }).selectOption("");
  await inspectNode(page, device);
  await expect(page.getByText(/Position: canonical \(switch\)/)).toBeVisible();

  // Self-contained triangle exercises real GLTFLoader geometry/material creation.
  const positions = Buffer.from(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]).buffer);
  const model = {
    asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
    buffers: [{ uri: `data:application/octet-stream;base64,${positions.toString("base64")}`, byteLength: positions.length }],
    bufferViews: [{ buffer: 0, byteLength: positions.length }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: "VEC3", min: [0, 0, 0], max: [1, 1, 0] }],
  };
  await page.getByLabel("Campus model file", { exact: true }).setInputFiles({ name: "triangle.gltf", mimeType: "model/gltf+json", buffer: Buffer.from(JSON.stringify(model)) });
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  await page.getByLabel("Registration source").fill("browser-fixture");
  await page.getByRole("button", { name: "Apply local registration" }).click();
  await expect(page.getByText("Registration applied locally — unsaved.")).toBeVisible();
  await page.getByRole("link", { name: /^Overview/ }).click();
  expect(errors).toEqual([]);
});

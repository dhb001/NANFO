import { expect, test, type Page } from "@playwright/test";
import type { PutSpatialScene, SpatialSceneSnapshot, SpatialObject } from "../../src/shared/types/spatial";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";
import { expectInspectedNode } from "./support/twin";

const device = "00000000-0000-0000-0000-000000000444";
const envelope = (data: unknown) => ({ success: true, data, meta: { next_cursor: null }, errors: null });
function fixture(): SpatialSceneSnapshot {
  const object = (id: string, type: SpatialObject["object_type"], parent: string | null, geometry?: SpatialObject["geometry"]): SpatialObject => ({
    object_id: id, name: id, object_type: type, parent_id: parent, device_id: type === "device" ? device : null,
    position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "browser-fixture", accuracy_m: null },
    ...(geometry ? { geometry } : {}),
  });
  const objects = [object("building", "building", null, { kind: "box", width: 20, depth: 12, height: 8 }),
    object("lower", "floor", "building", { kind: "slab", width: 20, depth: 12, thickness: 0.2 }),
    object("upper", "floor", "building", { kind: "slab", width: 20, depth: 12, thickness: 0.2 }),
    object("room", "room", "lower", { kind: "box", width: 12, depth: 10, height: 3 }),
    object("wall", "wall", "room", { kind: "wall", length: 8, height: 3, thickness: 0.2, material: { name: "brick", attenuation_db: null, source: "operator-survey" } }),
    object("switch", "device", "lower"), object("unknown-rack", "rack", "lower")];
  objects[0].position = { x: 100, y: 0, z: 40 }; objects[0].rotation.y = Math.PI / 2;
  objects[2].position.y = 4; objects[5].position.y = 1;
  return { version: 1, revision: 3, coordinate_system: { units: "m", up_axis: "y" }, objects };
}

// Inspect the actual R3F WebGL scene, not a second test-only renderer/model.
async function rendered(page: Page) {
  return page.evaluate(async () => {
    // ESM identity includes Vite's version query. An unversioned import creates
    // another R3F registry instead of inspecting the module that owns this Canvas.
    const modules = [...new Set(performance.getEntriesByType("resource").map((entry) => entry.name)
      .filter((name) => new URL(name).pathname === "/node_modules/.vite/deps/@react-three_fiber.js"))];
    if (modules.length !== 1) throw new Error(`Expected one loaded R3F module, found ${modules.length}.`);
    const { _roots } = await import(/* @vite-ignore */ modules[0]);
    // Canvas DOM visibility precedes its asynchronous R3F root registration.
    const deadline = performance.now() + 5000;
    let root = _roots.get(document.querySelector("canvas"));
    while (!root && performance.now() < deadline) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      root = _roots.get(document.querySelector("canvas"));
    }
    if (!root) throw new Error("The loaded R3F module does not own the visible Canvas.");
    const state = root.store.getState();
    // Canonical geometry is one InstancedMesh per floor and material class (FE-Twin fix 3):
    // each instance is a unit box scaled to the object's size, so decompose instance matrices.
    const instances: { size: number[]; world: number[]; opacity: number; clipping: number }[] = [];
    const round = (value: number) => Math.round(value * 1000) / 1000;
    state.scene.traverseVisible((object: any) => {
      if (!object.isInstancedMesh || !String(object.name).startsWith("canonical:")) return;
      const local = object.matrixWorld.clone(); const world = object.matrixWorld.clone();
      const position = object.position.clone(); const quaternion = object.quaternion.clone(); const scale = object.scale.clone();
      for (let index = 0; index < object.count; index++) {
        object.getMatrixAt(index, local);
        world.multiplyMatrices(object.matrixWorld, local).decompose(position, quaternion, scale);
        instances.push({ size: scale.toArray().map(round), world: position.toArray().map(round), opacity: object.material.opacity, clipping: object.material.clippingPlanes?.length ?? 0 });
      }
    });
    const point = state.camera.position.clone().set(100, 1, 40).project(state.camera);
    return { instances, deviceScreen: [(point.x + 1) / 2, (1 - point.y) / 2], camera: state.camera.position.toArray() as number[] };
  }).then(({ instances, ...view }) => ({ ...view, shapes: instances.map((shape) => ({ ...shape, id: fixtureObjectId(shape) })).sort((a, b) => a.id.localeCompare(b.id)) }));
}

// Instances carry no object ids: identify the fixture's objects by their exact canonical size (and floor height).
function fixtureObjectId(shape: { size: number[]; world: number[] }): string {
  const [x, y, z] = shape.size;
  if (x === 20 && y === 8 && z === 12) return "building";
  if (x === 20 && y === 0.2 && z === 12) return shape.world[1] > 2 ? "upper" : "lower";
  if (x === 12 && y === 3 && z === 10) return "room";
  if (y === 3 && z === 0.2) return "wall";
  return `unknown:${shape.size.join("x")}`;
}

test("dimension JSON saves real rotated geometry, clips/selects floors, picks instanced devices and restores omitted shapes", async ({ page }, testInfo) => {
  test.setTimeout(60000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await installSessionMocks(page, createDefaultSessionState());
  let server = fixture();
  const historical = { ...fixture(), revision: 1, objects: fixture().objects.map((object) => { delete object.geometry; return object; }) };
  const writes: PutSpatialScene[] = [];
  const node = { device_id: device, hostname: "geometry-switch", device_type: "switch", status: "active", spatial_ref_id: null };
  await page.route("**/api/v1/topology/graph?**", (route) => route.fulfill({ json: envelope({ nodes: [node], edges: [] }) }));
  await page.route("**/api/v1/topology/nodes/**", (route) => route.fulfill({ json: envelope({ node, neighbours: [] }) }));
  await page.route("**/spatial-scene", (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as PutSpatialScene; writes.push(body);
      expect(body.expected_revision).toBe(server.revision);
      server = { ...body.scene, revision: server.revision + 1 };
    }
    return route.fulfill({ json: envelope(server) });
  });
  await page.route("**/spatial-scene/history?**", (route) => route.fulfill({ json: envelope({ items: [{ revision: 1, origin: "baseline", actor_id: null, recorded_at: "2026-09-20T00:00:00Z", object_count: historical.objects.length }], page: 1, page_size: 20, total: 1 }) }));
  await page.route("**/spatial-scene/history/1", (route) => route.fulfill({ json: envelope(historical) }));
  await page.routeWebSocket(/\/ws\//, (socket) => socket.onMessage((message) => {
    const request = JSON.parse(String(message)); socket.send(JSON.stringify({ event: "subscribed", channel: request.channel, filters: request.filters }));
  }));
  await loginFromUi(page); await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await expect(page.getByText(/Server revision 3/)).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  await expect.poll(async () => (await rendered(page)).shapes.length).toBe(5);
  await expect.poll(async () => (await rendered(page)).shapes.find((shape) => shape.id === "wall")?.world).toEqual([100, 1.5, 36]);
  let view = await rendered(page);
  expect(view.shapes.find((shape) => shape.id === "wall")).toMatchObject({ size: [8, 3, 0.2], world: [100, 1.5, 36] });
  expect(view.shapes.find((shape) => shape.id === "room")!.opacity).toBeLessThan(0.2);
  expect(view.shapes.some((shape) => shape.id === "unknown-rack")).toBe(false);
  await expect(page.locator(".twin-label--geometry", { hasText: /^wall · / })).toContainText("brick · attenuation unknown · operator-survey");
  await page.locator("canvas").scrollIntoViewIfNeeded();
  await expect.poll(async () => (await rendered(page)).camera[0]).toBeGreaterThan(100);
  await page.screenshot({ path: testInfo.outputPath("canonical-geometry.png") });

  const editor = page.getByLabel("Spatial scene JSON", { exact: true });
  const draft = JSON.parse(await editor.inputValue()); draft.objects[4].geometry.length = -1;
  await editor.fill(JSON.stringify(draft)); await page.getByRole("button", { name: "Validate JSON", exact: true }).click();
  await expect(page.getByText(/Invalid geometry:/)).toBeVisible(); expect(writes).toHaveLength(0);
  draft.objects[4].geometry.length = 10;
  await editor.fill(JSON.stringify(draft)); page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save scene replacement" }).click();
  await expect(page.getByText("Saved revision 4.")).toBeVisible();
  await expect.poll(async () => (await rendered(page)).shapes.find((shape) => shape.id === "wall")?.size[0]).toBe(10);
  expect(writes[0].scene.objects[4].geometry).toEqual(draft.objects[4].geometry);

  await page.getByLabel("Canonical floor", { exact: true }).selectOption("lower");
  await expect.poll(async () => (await rendered(page)).shapes.map((shape) => shape.id)).toEqual(["lower", "room", "wall"]);
  await page.getByLabel("Clip above floor (m)", { exact: true }).fill("2");
  await expect.poll(async () => (await rendered(page)).shapes.every((shape) => shape.clipping === 1)).toBe(true);
  await expect(page.locator(".twin-label--geometry", { hasText: /^wall · / })).toHaveCount(0);
  await page.locator("canvas").scrollIntoViewIfNeeded();
  view = await rendered(page);
  const box = (await page.locator("canvas").boundingBox())!;
  await page.locator("canvas").click({ position: { x: view.deviceScreen[0] * box.width, y: view.deviceScreen[1] * box.height } });
  await expectInspectedNode(page, device);
  await page.getByLabel("Canonical floor", { exact: true }).selectOption("upper");
  await expect.poll(async () => (await rendered(page)).shapes.map((shape) => shape.id)).toEqual(["upper"]);
  await page.getByRole("button", { name: "Browse spatial history" }).click();
  await page.getByRole("button", { name: "Revision 1", exact: true }).click();
  await expect(page.getByText(/Restore revision 1 over current 4/)).toContainText("changed 5");
  await page.getByRole("button", { name: "Stage revision 1 for restore" }).click();
  await page.getByRole("button", { name: "Save scene replacement" }).click();
  await expect(page.getByText("Saved revision 5.")).toBeVisible();
  expect(writes[1].scene.objects).toEqual(historical.objects);
  expect(writes[1].scene.objects.every((object) => !Object.hasOwn(object, "geometry"))).toBe(true);
  await expect.poll(async () => (await rendered(page)).shapes.length).toBe(0);
  expect(errors).toEqual([]);
});

import { cpus, platform, release } from "node:os";
import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import type { PutSpatialScene, SpatialSceneSnapshot } from "../../src/shared/types/spatial";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";
import { rfFixture, rfFixtureScene } from "../../src/features/digitalTwin/rfFixture.test-data";

const device = "00000000-0000-0000-0000-000000000444";
const envelope = (data: unknown) => ({ success: true, data, meta: { next_cursor: null }, errors: null });
function scene(count = 1): SpatialSceneSnapshot {
  return { version: 1, revision: 3, coordinate_system: { units: "m", up_axis: "y" }, objects: Array.from({ length: count }, (_, i) => ({
    object_id: `placement-${i}`, parent_id: null, object_type: "device", name: `edge-${i}`,
    device_id: i === 0 ? device : `00000000-0000-0000-0001-${String(i).padStart(12, "0")}`,
    position: i === 0 ? { x: 0, y: 0, z: 0 } : { x: (i % 32) * 3 - 48, y: 0, z: -12 - Math.floor(i / 32) * 3 },
    rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "browser-fixture", accuracy_m: null },
  })) };
}
async function fixtures(page: Page, initial: SpatialSceneSnapshot) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await installSessionMocks(page, createDefaultSessionState());
  const nodes = initial.objects.filter((object) => object.device_id).map((object) => ({ device_id: object.device_id, hostname: object.name, device_type: "switch", status: "active", spatial_ref_id: null }));
  await page.route("**/api/v1/topology/graph?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    const start = Number(params.get("cursor") ?? 0);
    const limit = Number(params.get("limit") ?? 200);
    const end = Math.min(nodes.length, start + limit);
    return route.fulfill({ json: { ...envelope({ nodes: nodes.slice(start, end), edges: [] }), meta: { next_cursor: end < nodes.length ? String(end) : null } } });
  });
  await page.route("**/api/v1/topology/nodes/**", (route) => route.fulfill({ json: envelope({ node: nodes[0], neighbours: [] }) }));
  await page.route("**/spatial-scene", (route) => route.fulfill({ json: envelope(initial) }));
  await page.routeWebSocket(/\/ws\//, (socket) => socket.onMessage((message) => {
    const request = JSON.parse(String(message));
    socket.send(JSON.stringify({ event: "subscribed", channel: request.channel, filters: request.filters }));
  }));
  return errors;
}
async function openTwin(page: Page) {
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await expect(page.getByText(/Server revision 3/)).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
}

test("canonical fixture GET/PUT retains a conflicted draft and selection until explicit rebase/save", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  let server = scene();
  const errors = await fixtures(page, server);
  const writes: PutSpatialScene[] = [];
  await page.route("**/spatial-scene", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as PutSpatialScene;
      writes.push(body);
      if (writes.length === 1) {
        server = { ...server, revision: 4 };
        await route.fulfill({ status: 409, json: { success: false, data: null, meta: {}, errors: { code: "SPATIAL_REVISION_CONFLICT", message: "Fixture conflict" } } });
        return;
      }
      expect(body.expected_revision).toBe(server.revision);
      server = { ...body.scene, revision: server.revision + 1 };
    }
    await route.fulfill({ json: envelope(server) });
  });
  await openTwin(page);
  await page.getByLabel("Inspect node").selectOption(device);
  await expect(page.getByText(/Position: canonical \(placement-0\)/)).toBeVisible();
  const initial = scene();
  const draftScene = { version: initial.version, coordinate_system: initial.coordinate_system, objects: initial.objects };
  draftScene.objects[0].position.x = 12;
  const draft = JSON.stringify(draftScene, null, 2);
  await page.getByLabel("Spatial scene JSON", { exact: true }).fill(draft);
  expect(writes).toHaveLength(0);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save scene replacement" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Revision conflict" })).toContainText("Your draft is retained");
  await expect(page.getByLabel("Spatial scene JSON", { exact: true })).toHaveValue(draft);
  await expect(page.getByRole("button", { name: "Save scene replacement" })).toBeDisabled();
  await page.getByRole("button", { name: "Reload server scene" }).click();
  await page.getByRole("button", { name: "Rebase draft to revision 4" }).click();
  expect(writes).toHaveLength(1);
  await page.getByRole("button", { name: "Save scene replacement" }).click();
  await expect(page.getByText("Saved revision 5.")).toBeVisible();
  await expect(page.getByLabel("Inspect node")).toHaveValue(device);
  await expect(page.getByText(/\(12.00, 0.00, 0.00\) m/)).toBeVisible();
  expect(writes).toEqual([{ expected_revision: 3, scene: draftScene }, { expected_revision: 4, scene: draftScene }]);
  expect(errors).toEqual([]);
});

test("registration controls require explicit valid local transforms and reset on asset replacement", async ({ page }) => {
  const errors = await fixtures(page, scene());
  let asset: Record<string, unknown> | null = null;
  let downloads = 0;
  await page.route("**/campus/model-assets", async (route) => {
    if (route.request().method() === "POST") asset = { ...route.request().postDataJSON(), campus_model_asset_id: "saved-asset", network_id: "00000000-0000-0000-0000-000000000333", storage_backend: "local_cas", created_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z" };
    await route.fulfill({ json: envelope({ items: asset ? [asset] : [], total: asset ? 1 : 0 }) });
  });
  await page.route("**/campus-model-assets/saved-asset/download", async (route) => {
    downloads++;
    expect(route.request().headers().authorization).toContain("Bearer ");
    const bytes = Buffer.from(asset!.model_data_base64 as string, "base64");
    await route.fulfill({ body: bytes, contentType: "model/gltf+json", headers: { ETag: `"${createHash("sha256").update(bytes).digest("hex")}"` } });
  });
  await openTwin(page);
  // A valid self-contained glTF, not a claim about a live asset service.
  const model = { name: "campus.gltf", mimeType: "model/gltf+json", buffer: Buffer.from(JSON.stringify({ asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ name: "root" }] })) };
  await page.getByLabel("Campus model file", { exact: true }).setInputFiles(model);
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  await page.getByLabel("Registration source").fill("operator-survey");
  await page.getByLabel("Scale X", { exact: true }).fill("0");
  await expect(page.getByRole("button", { name: "Apply local registration" })).toBeDisabled();
  await page.getByLabel("Scale X", { exact: true }).fill("0.01");
  await page.getByLabel("Scale Y", { exact: true }).fill("0.02");
  await page.getByLabel("Position X", { exact: true }).fill("12");
  await page.getByLabel("Rotation Y", { exact: true }).fill("1.5707963267948966");
  await page.getByRole("button", { name: "Apply local registration" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Registration applied locally — unsaved.")).toBeVisible();
  await page.getByRole("button", { name: "Persist Model Asset", exact: true }).click();
  await expect(page.getByText("Model registration — saved", { exact: true })).toBeVisible();
  expect(asset!.registration).toMatchObject({ translation: { x: 12, y: 0, z: 0 }, scale: { x: 0.01, y: 0.02, z: 1 }, source: "operator-survey" });
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("combobox", { name: "Persisted model asset", exact: true }).selectOption("saved-asset");
  await page.getByRole("button", { name: "Restore Persisted Model" }).click();
  await expect.poll(() => downloads).toBe(1);
  await expect(page.getByLabel("Scale Y", { exact: true })).toHaveValue("0.02");
  await expect(page.getByText("Model registration — saved", { exact: true })).toBeVisible();
  await page.getByLabel("Campus model file", { exact: true }).setInputFiles({ ...model, name: "replacement.gltf" });
  await expect(page.getByText("Finite transforms, positive scale and source required.")).toBeVisible();
  await expect(page.getByLabel("Scale X", { exact: true })).toHaveValue("1");
  expect(errors).toEqual([]);
});

test("history browse/diff restores as a new revision using the current PUT", async ({ page }) => {
  const errors = await fixtures(page, scene());
  const historical = scene(); historical.revision = 1; historical.objects[0].position.x = 7;
  await page.route("**/spatial-scene/history?**", (route) => route.fulfill({ json: envelope({ items: [{ revision: 1, origin: "baseline", actor_id: null, recorded_at: "2026-09-20T00:00:00Z", object_count: 1 }], page: 1, page_size: 20, total: 1 }) }));
  await page.route("**/spatial-scene/history/1", (route) => route.fulfill({ json: envelope(historical) }));
  let writes = 0;
  await page.route("**/spatial-scene", async (route) => {
    if (route.request().method() === "PUT") {
      writes++; const body = route.request().postDataJSON();
      expect(body.expected_revision).toBe(3); expect(body.scene.revision).toBeUndefined();
      await route.fulfill({ json: envelope({ ...body.scene, revision: 4 }) });
    } else await route.fulfill({ json: envelope(scene()) });
  });
  await openTwin(page);
  await page.getByRole("button", { name: "Browse spatial history" }).click();
  await page.getByRole("button", { name: "Revision 1", exact: true }).click();
  await expect(page.getByText(/Restore revision 1 over current 3/)).toContainText("changed 1");
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Stage revision 1 for restore" }).click();
  expect(writes).toBe(0);
  await page.getByRole("button", { name: "Save scene replacement" }).click();
  await expect(page.getByText("Saved revision 4.")).toBeVisible();
  expect(writes).toBe(1); expect(errors).toEqual([]);
});

test("operator artifact renders modeled RSSI only on its verified canonical snapshot", async ({ page }) => {
  const errors = await fixtures(page, rfFixtureScene);
  // Scope IDs are the actual backend-generated fixture; no fabricated RF hashes.
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.evaluate(async () => {
    const path = "/src/shared/state/workspace-store.ts";
    const { useWorkspaceStore } = await import(/* @vite-ignore */ path);
    useWorkspaceStore.setState({ workspaceId: "workspace-1", networkId: "network-1" });
  });
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await page.getByRole("button", { name: "Operator RF samples", exact: true }).click();
  await page.getByLabel("Expected RF coordinate frame ID").fill("rf-z-up");
  await page.getByLabel("Backend spatial-rf artifacts").setInputFiles({ name: "rf.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(rfFixture)) });
  await expect(page.getByText("Imported 1 RF samples; alignment verified.")).toBeVisible();
  await expect(page.getByText(/rx-1: -49.1 dBm/).first()).toContainText("uncertainty unknown");
  await page.locator("canvas").scrollIntoViewIfNeeded();
  await expect(page.getByText("RF modeled rx-1: -49.1 dBm · uncertainty unknown", { exact: true })).toBeVisible();
  await page.route("**/spatial-scene", (route) => route.fulfill({ json: envelope({ ...rfFixtureScene, revision: 5 }) }));
  await page.getByRole("button", { name: "Reload server scene" }).click();
  await expect(page.getByText("Scene changed/unavailable: RF hidden. Reimport required.")).toBeVisible();
  await expect(page.getByText("RF modeled rx-1: -49.1 dBm · uncertainty unknown", { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("bounded 1024-device fixture benchmark and actual instanced canvas picking", async ({ page, browser }, testInfo) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    const metrics = { draws: 0, instances: 0 };
    Object.assign(window, { spatialBenchmark: metrics });
    const original = WebGL2RenderingContext.prototype.drawElementsInstanced;
    WebGL2RenderingContext.prototype.drawElementsInstanced = function (...args) {
      metrics.draws++; metrics.instances += args[4];
      return original.apply(this, args);
    };
  });
  const errors = await fixtures(page, scene(1024));
  await openTwin(page);
  const canvas = page.locator("canvas");
  await canvas.scrollIntoViewIfNeeded();
  await expect.poll(() => page.evaluate(() => (window as unknown as { spatialBenchmark: { draws: number } }).spatialBenchmark.draws)).toBeGreaterThan(0);
  const box = (await canvas.boundingBox())!;
  // The isolated origin device is at the initial orbit target; labels don't intercept picking.
  await canvas.click({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect(page.getByLabel("Inspect node")).toHaveValue(device);
  await expect.poll(() => page.locator("[data-device-label]").count()).toBeLessThanOrEqual(24);
  await canvas.scrollIntoViewIfNeeded();
  const measured = await page.evaluate(async () => {
    const metrics = (window as unknown as { spatialBenchmark: { draws: number; instances: number } }).spatialBenchmark;
    const gl = document.querySelector("canvas")!.getContext("webgl2")!;
    const debug = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    const start = performance.now(); const startDraws = metrics.draws; const startInstances = metrics.instances;
    const deltas: number[] = []; let previous = start;
    await new Promise<void>((resolve) => {
      function sample(now: number) {
        deltas.push(now - previous); previous = now;
        if (deltas.length >= 90 || now - start >= 6000) resolve(); else requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    });
    const sorted = [...deltas].sort((a, b) => a - b);
    return { frames: deltas.length, elapsedMs: previous - start, medianFrameMs: sorted[Math.floor(sorted.length / 2)], p95FrameMs: sorted[Math.floor(sorted.length * 0.95)],
      instancedDraws: metrics.draws - startDraws, submittedInstances: metrics.instances - startInstances, renderer, userAgent: navigator.userAgent, dpr: devicePixelRatio };
  });
  expect(measured.frames).toBeGreaterThan(1);
  expect(measured.instancedDraws).toBeGreaterThan(0);
  // Draw submissions scale with visual batches, not the 1024 devices. No FPS claim.
  expect(measured.instancedDraws / measured.frames).toBeLessThan(20);
  const report = {
    fixture: "1024 switches, congestion rings on, labels capped24/distance65m, no links/APs/models; reduced motion", mode: "Vite dev, headless fixture; not backend acceptance",
    browser: browser.version(), os: `${platform()} ${release()}`, cpu: cpus()[0]?.model, logicalCpus: cpus().length, viewport: { width: 1440, height: 1000 }, ...measured,
  };
  console.log("Dense scene reference:", JSON.stringify(report));
  await testInfo.attach("dense-scene-reference.json", { contentType: "application/json", body: JSON.stringify(report, null, 2) });
  expect(errors).toEqual([]);
});

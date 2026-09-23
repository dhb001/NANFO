import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";
import type { PutSpatialScene, SpatialSceneSnapshot } from "../../src/shared/types/spatial";

const envelope = (data: unknown) => ({ success: true, data, meta: { next_cursor: null }, errors: null });

test("guided object, paged custom membership and chosen asset retirement use exact confirmed contracts", async ({ page }) => {
  test.setTimeout(90000);
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  const state = createDefaultSessionState();
  const networkId = state.networks[0].network_id;
  const devices = Array.from({ length: 21 }, (_, i) => ({ ...state.devicesByNetwork[networkId][0], device_id: `00000000-0000-0000-0000-${String(i + 1).padStart(12, "0")}`, hostname: `inventory-${i + 1}`, spatial_ref_id: null }));
  state.devicesByNetwork[networkId] = devices;
  await installSessionMocks(page, state);
  await page.route("**/api/v1/topology/graph?**", (route) => route.fulfill({ json: envelope({ nodes: devices, edges: [] }) }));
  await page.route("**/api/v1/networks/*/devices?**", (route) => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get("page"));
    return route.fulfill({ json: envelope({ items: devices.slice((pageNumber - 1) * 20, pageNumber * 20), total: 21, page: pageNumber, page_size: 20 }) });
  });
  await page.routeWebSocket(/\/ws\//, (socket) => socket.onMessage((message) => {
    const request = JSON.parse(String(message)); socket.send(JSON.stringify({ event: "subscribed", channel: request.channel, filters: request.filters }));
  }));
  let scene: SpatialSceneSnapshot = { version: 1, revision: 0, coordinate_system: { units: "m", up_axis: "y" }, objects: [] };
  const sceneWrites: PutSpatialScene[] = [];
  await page.route("**/spatial-scene", (route) => {
    if (route.request().method() === "PUT") { const body = route.request().postDataJSON(); sceneWrites.push(body); scene = { ...body.scene, revision: 1 }; }
    return route.fulfill({ json: envelope(scene) });
  });
  const groupWrites: unknown[] = [];
  let groups: unknown[] = [];
  await page.route("**/device-groups", (route) => {
    if (route.request().method() === "POST") { const body = route.request().postDataJSON(); groupWrites.push(body); groups = body.groups; }
    return route.fulfill({ json: envelope({ items: groups, total: groups.length }) });
  });
  const buildingWrites: unknown[] = [];
  await page.route("**/campus/buildings", (route) => {
    if (route.request().method() === "POST") buildingWrites.push(route.request().postDataJSON());
    return route.fulfill({ json: envelope({ items: [], total: 0 }) });
  });
  const bytes = Buffer.from(JSON.stringify({ asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ name: "root" }] }));
  const model = { network_id: networkId, model_mime_type: "model/gltf+json", model_data_base64: bytes.toString("base64"), model_size_bytes: bytes.length, model_sha256: createHash("sha256").update(bytes).digest("hex"), mapping_by_device_id: {}, source: "browser-fixture", created_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z" };
  let assets = [{ ...model, campus_model_asset_id: "older", model_file_name: "older.gltf" }, { ...model, campus_model_asset_id: "newer", model_file_name: "newer.gltf" },
    ...Array.from({ length: 19 }, (_, i) => ({ ...model, campus_model_asset_id: `extra-${i}`, model_file_name: `extra-${i}.gltf` }))];
  const assetReads: number[] = [];
  await page.route("**/campus/model-assets?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    expect(params.get("include_data")).toBe("false"); expect(params.get("page_size")).toBe("20");
    const pageNumber = Number(params.get("page")); assetReads.push(pageNumber);
    return route.fulfill({ json: envelope({ items: assets.slice((pageNumber - 1) * 20, pageNumber * 20).map((asset) => ({ ...asset, model_data_base64: undefined })), total: assets.length, page: pageNumber, page_size: 20 }) });
  });
  await page.route("**/campus-model-assets/*/download", (route) => route.fulfill({ body: bytes, contentType: "application/octet-stream", headers: { ETag: `"sha256:${model.model_sha256}"`, "Content-Length": String(bytes.length) } }));
  const deletes: string[] = [];
  await page.route("**/campus/model-assets/*", (route) => {
    expect(route.request().method()).toBe("DELETE"); expect(route.request().postData()).toBeNull();
    const id = route.request().url().split("/").at(-1)!; deletes.push(id); assets = assets.filter((asset) => asset.campus_model_asset_id !== id);
    return route.fulfill({ status: 204 });
  });
  await loginFromUi(page); await page.locator("button.network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await expect(page.getByText(/Server revision 0/)).toBeVisible();
  await page.getByRole("button", { name: "Guided object editor" }).click();
  await page.getByLabel("Object ID", { exact: true }).fill("survey-building");
  await page.getByLabel("Object name", { exact: true }).fill("Survey building");
  for (const key of ["position", "rotation"]) for (const axis of ["x", "y", "z"]) await page.getByLabel(`${key} ${axis}`, { exact: true }).fill("0");
  await page.getByLabel("Provenance source", { exact: true }).fill("operator-survey");
  await page.getByRole("combobox", { name: "Geometry", exact: true }).selectOption("box");
  for (const [key, value] of [["width", "12"], ["depth", "8"], ["height", "3"]]) await page.getByLabel(key, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Stage object in draft" }).click();
  expect(sceneWrites).toHaveLength(0);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save scene replacement" }).click();
  await expect(page.getByText("Saved revision 1.")).toBeVisible();
  expect(sceneWrites).toEqual([{ expected_revision: 0, scene: { version: 1, coordinate_system: { units: "m", up_axis: "y" }, objects: [{ object_id: "survey-building", name: "Survey building", object_type: "building", parent_id: null, position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 }, provenance: { source: "operator-survey", accuracy_m: null }, device_id: null, geometry: { kind: "box", width: 12, depth: 8, height: 3 } }] } }]);

  await page.getByRole("button", { name: "Custom device groups", exact: true }).click();
  const editor = page.getByRole("region", { name: "Custom device groups" });
  await editor.getByLabel("Stable group key").fill("survey-ops"); await editor.getByLabel("Group name", { exact: true }).fill("Survey operations");
  await editor.getByRole("button", { name: "Next inventory page" }).click();
  await editor.getByLabel(/inventory-21 ·/).check();
  expect(groupWrites).toHaveLength(0);
  await editor.getByRole("button", { name: "Save custom group" }).click();
  await expect(editor.getByText("Custom group saved.")).toBeVisible();
  expect(groupWrites).toEqual([{ replace_existing: false, groups: [{ group_key: "survey-ops", name: "Survey operations", group_type: "custom", description: null, selector: {}, device_ids: [devices[20].device_id] }] }]);

  await page.getByRole("combobox", { name: "Persisted model asset", exact: true }).selectOption("older");
  await page.getByRole("button", { name: "Next asset page" }).click();
  await expect(page.getByText("Asset page 2 · 21 assets", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Persisted model asset", exact: true })).toHaveValue("older");
  expect(deletes).toEqual([]);
  await page.getByRole("button", { name: "Restore Persisted Model", exact: true }).click();
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  expect(assetReads.at(-1)).toBe(1);
  await page.getByLabel("Campus model file", { exact: true }).setInputFiles({ name: "unrelated.gltf", mimeType: "model/gltf+json", buffer: bytes });
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retire selected asset" }).click();
  await expect(page.getByText("Selected asset retired.")).toBeVisible();
  expect(deletes).toEqual(["older"]);
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Persisted model asset", exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Previous asset page" }).click();
  await page.getByRole("combobox", { name: "Persisted model asset", exact: true }).selectOption("newer");
  await page.getByRole("button", { name: "Restore Persisted Model", exact: true }).click();
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retire selected asset" }).click();
  await expect(page.getByText("model idle", { exact: true })).toBeVisible();
  expect(deletes).toEqual(["older", "newer"]);
  await page.getByText("Clear active groups or campus buildings", { exact: true }).click();
  await page.getByRole("button", { name: "Clear all persisted groups" }).click();
  await expect(page.getByText("All active groups cleared.")).toBeVisible();
  await page.getByRole("button", { name: "Clear all persisted buildings" }).click();
  await expect(page.getByText("All active buildings cleared.")).toBeVisible();
  expect(groupWrites.at(-1)).toEqual({ replace_existing: true, groups: [] });
  expect(buildingWrites).toEqual([{ buildings: [], replace_existing: true }]);
  expect(errors).toEqual([]);
});

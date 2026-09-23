import { createHash } from "node:crypto";
import { expect, test, type WebSocketRoute } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

const network = "00000000-0000-0000-0000-000000000333";
const device = "00000000-0000-0000-0000-000000000444";
const node = { device_id: device, hostname: "edge-1", device_type: "switch", status: "active", spatial_ref_id: null };
const envelope = (data: unknown) => ({ success: true, data, meta: { next_cursor: null }, errors: null });

function validGlb() {
  const json = JSON.stringify({ asset: { version: "2.0" }, scenes: [{ nodes: [0] }], scene: 0, nodes: [{ name: "campus" }] });
  const chunk = Buffer.from(json.padEnd(Math.ceil(json.length / 4) * 4, " "));
  const header = Buffer.alloc(20);
  [0x46546c67, 2, chunk.length + 20, chunk.length, 0x4e4f534a].forEach((value, index) => header.writeUInt32LE(value, index * 4));
  return Buffer.concat([header, chunk]);
}

test("valid GLB persistence and explicit restore validate hash, retain groups, and clean up URLs", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await installSessionMocks(page, createDefaultSessionState());
  await page.addInitScript(() => {
    const tracked = window as unknown as { modelUrls: string[]; revokedModelUrls: string[] };
    tracked.modelUrls = []; tracked.revokedModelUrls = [];
    const create = URL.createObjectURL.bind(URL);
    const revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (blob) => { const url = create(blob); tracked.modelUrls.push(url); return url; };
    URL.revokeObjectURL = (url) => { tracked.revokedModelUrls.push(url); revoke(url); };
  });
  await page.route("**/api/v1/topology/graph?**", (route) => route.fulfill({ json: envelope({ nodes: [node], edges: [] }) }));
  const bytes = validGlb();
  let record = { campus_model_asset_id: "asset", network_id: network, model_file_name: "saved.glb", model_mime_type: "model/gltf-binary", model_data_base64: bytes.toString("base64"), model_size_bytes: bytes.length,
    model_sha256: createHash("sha256").update(bytes).digest("hex"), mapping_by_device_id: { [device]: "campus/building/f1" }, source: "session_import", created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z" };
  await page.route(/\/campus\/model-assets(?:\?.*)?$/, async (route) => {
    if (route.request().method() === "POST") record = { ...record, ...route.request().postDataJSON() };
    await route.fulfill({ json: envelope({ items: [{ ...record, model_data_base64: undefined }], total: 1, page: 1, page_size: 20 }) });
  });
  await page.route("**/campus-model-assets/asset/download", (route) => route.fulfill({ body: bytes, contentType: "application/octet-stream", headers: { ETag: `"sha256:${record.model_sha256}"`, "Content-Length": String(bytes.length) } }));
  const unrelated = { group_key: "other-campus", name: "Other campus", group_type: "custom" };
  let groups = [unrelated];
  await page.route("**/device-groups", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      expect(body.replace_existing).toBe(false);
      groups = [...(body.replace_existing ? [] : groups), ...body.groups];
    }
    await route.fulfill({ json: envelope({ items: groups, total: groups.length }) });
  });
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await expect(page.getByText("model idle", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Restore Persisted Model" })).toBeDisabled();
  await page.getByRole("combobox", { name: "Persisted model asset", exact: true }).selectOption("asset");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Restore Persisted Model" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("model ready", { exact: true })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Inspect node").selectOption(device);
  await expect(page.getByText("spatial_ref_id: campus/building/f1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Persist Device Groups" }).click();
  await expect.poll(() => groups.length).toBe(3);
  expect(groups).toContainEqual(unrelated);
  await page.getByLabel("Campus model file").setInputFiles({ name: "local.glb", mimeType: "model/gltf-binary", buffer: bytes });
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Restore Persisted Model" }).click();
  await expect(page.getByText("model: local.glb", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Persist Model Asset" }).click();
  await expect.poll(() => record.model_file_name).toBe("local.glb");
  record = { ...record, model_sha256: "0".repeat(64) };
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("link", { name: /^Overview/ }).click();
  await expect.poll(() => page.evaluate(() => {
    const tracked = window as unknown as { modelUrls: string[]; revokedModelUrls: string[] };
    return tracked.modelUrls.every((url) => tracked.revokedModelUrls.includes(url));
  })).toBe(true);
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await page.getByRole("combobox", { name: "Persisted model asset", exact: true }).selectOption("asset");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Restore Persisted Model" }).click();
  await expect(page.getByText("Persisted model SHA-256 verification failed.")).toBeVisible();
  await expect(page.getByText("model idle", { exact: true })).toBeVisible();
});

test("subscribed reconnect reconciles deleted REST nodes and ignores stale pushes", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  let nodes = [node];
  let graphReads = 0;
  let topology: WebSocketRoute | undefined;
  await page.route("**/api/v1/topology/graph?**", (route) => { graphReads += 1; return route.fulfill({ json: envelope({ nodes, edges: [] }) }); });
  await page.routeWebSocket(/\/ws\//, (socket) => {
    socket.onMessage((message) => {
      const subscription = JSON.parse(String(message));
      socket.send(JSON.stringify({ event: "subscribed", channel: subscription.channel, filters: subscription.filters }));
      if (subscription.channel === "topology") topology = socket;
    });
  });
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await expect(page.getByText("topology open", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Inspect node").locator("option", { hasText: "edge-1" })).toHaveCount(1);
  await expect.poll(() => Boolean(topology)).toBe(true);
  topology!.send(JSON.stringify({ event: "topology.device.removed", timestamp: "2026-09-10T00:02:00Z", data: { delta_type: "remove", node: { device_id: device } } }));
  topology!.send(JSON.stringify({ event: "topology.device.added", timestamp: "2026-09-10T00:01:00Z", data: { delta_type: "add", node } }));
  await expect(page.getByLabel("Inspect node").locator("option", { hasText: "edge-1" })).toHaveCount(0);
  nodes = [];
  const previousReads = graphReads;
  const oldSocket = topology!;
  oldSocket.close({ code: 1012, reason: "restart" });
  await expect.poll(() => topology !== oldSocket).toBe(true);
  await expect.poll(() => graphReads).toBeGreaterThan(previousReads);
  await expect(page.getByText("Topology graph is empty")).toBeVisible();
  topology!.send(JSON.stringify({ event: "topology.device.added", timestamp: "2026-09-10T00:01:00Z", data: { delta_type: "add", node } }));
  await expect(page.getByLabel("Inspect node").locator("option", { hasText: "edge-1" })).toHaveCount(0);
});

test("Twin-only lifecycle overlays reconcile known details after reconnect/backpressure and retire denied IDs", async ({ page }) => {
  const session = createDefaultSessionState();
  await installSessionMocks(page, session);
  const simulationId = "00000000-0000-0000-0000-000000000701";
  const intentId = "00000000-0000-0000-0000-000000000702";
  let status = "running";
  let denied = false;
  let reads = 0;
  let twin: WebSocketRoute | undefined;
  await page.route("**/api/v1/simulations/*", (route) => {
    reads++;
    return route.fulfill({ json: envelope({ simulation_id: simulationId, workspace_id: session.workspaceId, network_id: "00000000-0000-0000-0000-000000000333",
      status, state: status, risk_gate: "blocked", revision: status === "running" ? 1 : 2, updated_at: status === "running" ? "2026-09-10T00:00:00Z" : "2026-09-10T00:01:00Z" }) });
  });
  await page.route("**/api/v1/intents/*?*", (route) => denied
    ? route.fulfill({ status: 403, json: { success: false, data: null, meta: {}, errors: { code: "DENIED", message: "Unavailable" } } })
    : route.fulfill({ json: envelope({ intent_id: intentId, workspace_id: session.workspaceId, network_id: "00000000-0000-0000-0000-000000000333", status: "execution_started", execution_provenance: {}, updated_at: "2026-09-10T00:00:00Z" }) }));
  await page.routeWebSocket(/\/ws\//, (socket) => socket.onMessage((message) => {
    const subscription = JSON.parse(String(message));
    socket.send(JSON.stringify({ event: "subscribed", channel: subscription.channel, filters: subscription.filters }));
    if (subscription.channel === "digital-twin") twin = socket;
  }));
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: "Digital Twin" }).click();
  await expect.poll(() => Boolean(twin)).toBe(true);
  for (const [kind, id] of [["simulation", simulationId], ["intent", intentId]]) twin!.send(JSON.stringify({ event: `${kind}.started`, timestamp: "2026-09-10T00:00:00Z", data: {
    delta_type: "update", scene_object: { id: "legacy", object_type: `${kind}_state`, [`${kind}_id`]: id, status: kind === "simulation" ? "running" : "execution_started" },
  } }));
  const region = page.getByRole("region", { name: "Live Scene Deltas", exact: true });
  await expect(region.getByText("running", { exact: true })).toBeVisible();
  await expect.poll(() => reads).toBeGreaterThan(0);
  status = "completed";
  const old = twin!; old.close({ code: 1012, reason: "restart" });
  await expect.poll(() => twin !== old).toBe(true);
  await expect(region.getByText("completed", { exact: true })).toBeVisible();
  await expect(region.getByText(/Detail reconciliation: reconciled/).first()).toBeVisible();
  denied = true;
  twin!.send(JSON.stringify({ event: "error", data: { code: "WS_BACKPRESSURE", message: "Backlog" } }));
  await expect(region.getByText(`intent:${intentId}`, { exact: true })).toHaveCount(0);
  await expect(region.getByText(/Partial known-object view only/)).toBeVisible();
});

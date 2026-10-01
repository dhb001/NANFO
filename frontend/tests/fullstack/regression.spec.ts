import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";
import { api, apiOrigin, fixture, login, loopback, origins, pathResponse, selectNetwork, session, triangle } from "./support";

test.beforeEach(async ({ page }) => {
  page.on("pageerror", (error) => { throw error; });
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("persisted paginated inventory, tenant denial and UI tenancy mutation survive reload", async ({ page, request }) => {
  await login(page);
  await selectNetwork(page);
  const token = (await session(page)).accessToken;
  const pagination = page.getByRole("navigation", { name: "Networks pagination" });
  await expect(pagination).toContainText("21 total");
  await pagination.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("button.network-choice")).toHaveCount(1);
  await pagination.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("navigation", { name: "Devices pagination" }).getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: "Edit r09-device-21", exact: true })).toBeVisible();
  await api(request, token, "GET", `/api/v1/networks?workspace_id=${fixture.outsider.workspace_id}`, undefined, 403);
  await page.getByText("Create a network", { exact: true }).click();
  const form = page.getByRole("form", { name: "Create network" });
  await form.getByLabel("Network name").fill("R09 browser-created");
  const createdResponse = pathResponse(page, "/api/v1/networks", "POST");
  await form.getByRole("button", { name: "Create Network", exact: true }).click();
  const created = await createdResponse;
  expect(created.status()).toBe(201);
  const network = (await created.json()).data;
  await expect(page.getByText("Selected network: R09 browser-created", { exact: true })).toBeVisible();
  await page.reload();
  const persisted = (await api(request, token, "GET", `/api/v1/networks?workspace_id=${fixture.owner.workspace_id}&page=2&page_size=20`)).items.find((item: { network_id: string }) => item.network_id === network.network_id);
  expect(persisted.name).toBe("R09 browser-created");
  await page.getByRole("navigation", { name: "Networks pagination" }).getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Selected network: R09 browser-created", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Tenancy", exact: true }).click();
  const workspace = page.getByRole("form", { name: "Create workspace" });
  await workspace.getByLabel("Workspace Name").fill("R09 browser workspace");
  const workspaceResponse = pathResponse(page, `/api/v1/organizations/${fixture.owner.org_id}/workspaces`, "POST");
  await workspace.getByRole("button", { name: "Create Workspace", exact: true }).click();
  const receipt = await workspaceResponse;
  expect(receipt.status()).toBe(201);
  const workspaceId = (await receipt.json()).data.workspace_id;
  await expect(page.getByText(`Selected workspace: ${workspaceId}`, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(`Selected workspace: ${workspaceId}`, { exact: true })).toBeVisible();
  const saved = await api(request, token, "GET", `/api/v1/organizations/${fixture.owner.org_id}/workspaces/${workspaceId}`);
  expect(saved.name).toBe("R09 browser workspace");
});

test("real CAS upload, metadata-only pagination, reload and binary-header restore", async ({ page, request }) => {
  await login(page);
  await selectNetwork(page);
  const token = (await session(page)).accessToken;
  const network = fixture.owner.network_id;
  const assetPath = `/api/v1/networks/${network}/campus/model-assets`;
  const metadataResponse = pathResponse(page, assetPath);
  await page.getByRole("link", { name: "Digital Twin", exact: true }).click();
  const metadata = await metadataResponse;
  expect(new URL(metadata.url()).searchParams.get("include_data")).toBe("false");
  expect(new URL(metadata.url()).searchParams.get("page_size")).toBe("20");
  await expect(page.locator("canvas")).toBeVisible();
  const bytes = triangle();
  const digest = createHash("sha256").update(bytes).digest("hex");
  await page.getByLabel("Campus model file", { exact: true }).setInputFiles({ name: "r09-triangle.gltf", mimeType: "model/gltf+json", buffer: bytes });
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();
  await page.getByLabel("Registration source").fill("r09-regression-fixture");
  await page.getByRole("button", { name: "Apply local registration", exact: true }).click();
  const uploadResponse = pathResponse(page, assetPath, "POST");
  await page.getByRole("button", { name: "Persist Model Asset", exact: true }).click();
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(200);
  const asset = (await uploaded.json()).data.items.find((item: { model_sha256: string }) => item.model_sha256 === digest);
  expect(asset.storage_backend).toBe("local_cas");
  expect(asset.model_size_bytes).toBe(bytes.length);
  expect(asset.registration).not.toBeNull();
  await expect(page.getByText("Campus model asset persisted", { exact: true })).toBeVisible();

  // Restore the exact UI-uploaded asset across a real browser reload.
  await page.reload();
  await expect(page.getByText("model idle", { exact: true })).toBeVisible();
  const selector = page.getByRole("combobox", { name: "Persisted model asset", exact: true });
  await expect(selector.locator("option")).not.toHaveCount(1);
  await selector.selectOption(asset.campus_model_asset_id);
  page.on("dialog", (dialog) => dialog.accept());
  const binaryPath = `/api/v1/networks/${network}/campus-model-assets/${asset.campus_model_asset_id}/download`;
  const binaryResponse = pathResponse(page, binaryPath);
  await page.getByRole("button", { name: "Restore Persisted Model", exact: true }).click();
  const binary = await binaryResponse;
  expect(binary.status()).toBe(200);
  expect(binary.headers()["content-type"]).toBe("application/octet-stream");
  expect(binary.headers().etag).toBe(`"sha256:${digest}"`);
  expect(await binary.body()).toEqual(bytes);
  await expect(page.getByText("model ready", { exact: true })).toBeVisible();

  // Distinct bytes are required: the real service updates, rather than duplicates, the latest identical asset.
  for (let index = 0; index < 20; index++) {
    const pagedBytes = Buffer.from(JSON.stringify({ ...JSON.parse(bytes.toString()), extras: { r09: index } }));
    await api(request, token, "POST", assetPath, {
      model_file_name: `r09-page-${index.toString().padStart(2, "0")}.gltf`, model_mime_type: "model/gltf+json",
      model_data_base64: pagedBytes.toString("base64"), model_sha256: createHash("sha256").update(pagedBytes).digest("hex"), model_size_bytes: pagedBytes.length,
      mapping_by_device_id: {}, source: "r09-regression-fixture", replace_existing: false,
    });
  }
  const pages = await Promise.all([1, 2].map((p) => api(request, token, "GET", `${assetPath}?include_data=false&page=${p}&page_size=20`)));
  expect(pages.map((p) => p.items.length)).toEqual([20, 1]);
  expect(pages.map((p) => p.total)).toEqual([21, 21]);
  const ids = pages.flatMap((p) => p.items.map((item: { campus_model_asset_id: string }) => item.campus_model_asset_id));
  expect(new Set(ids).size).toBe(21);
  for (const p of pages) for (const item of p.items) expect(item).not.toHaveProperty("model_data_base64");
  expect((await api(request, token, "GET", `${assetPath}?include_data=false&page=2&page_size=20`)).items).toEqual(pages[1].items);
  await api(request, token, "GET", `${assetPath}?include_data=false&page=1&page_size=101`, undefined, 422);
  await page.getByRole("button", { name: "Reload persisted Twin records", exact: true }).click();
  const nextPage = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === assetPath && url.searchParams.get("page") === "2";
  });
  await page.getByRole("button", { name: "Next asset page", exact: true }).click();
  const next = await nextPage;
  expect(new URL(next.url()).searchParams.get("page")).toBe("2");
  expect(new URL(next.url()).searchParams.get("include_data")).toBe("false");
  await expect(selector.locator(`option[value="${pages[1].items[0].campus_model_asset_id}"]`)).toHaveCount(1);

  const { email, password } = fixture.users.outsider;
  const foreign = await request.post(`${apiOrigin}/api/v1/auth/login`, { data: { email, password } });
  expect(foreign.status()).toBe(200);
  const foreignToken = (await foreign.json()).data.access_token;
  await api(request, foreignToken, "GET", `${assetPath}?include_data=false&page=1&page_size=20`, undefined, 403);
  await api(request, foreignToken, "GET", binaryPath, undefined, 403);
});

test("independent report worker produces a persisted downloadable verified CSV", async ({ page }) => {
  await login(page);
  await selectNetwork(page);
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await page.getByLabel("Output Format").selectOption("csv");
  await page.getByRole("button", { name: "Generate Report", exact: true }).click();
  await expect(page.getByText("status generated", { exact: true })).toBeVisible({ timeout: 60_000 });
  const downloaded = page.waitForEvent("download");
  const response = page.waitForResponse((r) => /\/api\/v1\/reports\/[^/]+\/download/.test(r.url()));
  await page.getByRole("button", { name: "Download CSV", exact: true }).click();
  const download = await downloaded;
  const stream = await download.createReadStream();
  expect(stream).not.toBeNull();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const bytes = Buffer.concat(chunks);
  expect(bytes.length).toBeGreaterThan(0);
  expect(bytes).toEqual(await (await response).body());
  await expect(page.getByRole("status").filter({ hasText: "actual bytes received" })).toContainText(`${bytes.length} actual bytes received; SHA-256 verified`);
  await page.reload();
  await page.getByRole("button", { name: "Refresh History", exact: true }).click();
  await expect(page.getByRole("button", { name: /executive_summary \/.*generated/ })).toBeVisible();
});

test("independent simulation worker completes configured model and persists history", async ({ page, request }) => {
  await login(page);
  await selectNetwork(page);
  await page.getByRole("link", { name: "Simulation", exact: true }).click();
  const started = pathResponse(page, "/api/v1/simulations/start", "POST");
  await page.getByRole("button", { name: "Start Simulation", exact: true }).click();
  const response = await started;
  expect(response.status()).toBe(202);
  const id = (await response.json()).data.simulation_id;
  const token = (await session(page)).accessToken;
  await expect.poll(async () => (await api(request, token, "GET", `/api/v1/simulations/${id}`)).status, { timeout: 60_000 }).toBe("completed");
  const saved = await api(request, token, "GET", `/api/v1/simulations/${id}`);
  expect(saved.run_output.source).toBe("operator_configured_model");
  expect(saved.run_output.physical_safety_authorized).toBe(false);
  expect(saved.run_output.output_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(saved.run_output.trace.length).toBeGreaterThan(0);
  await page.reload();
  await page.getByRole("button", { name: "Refresh simulation history", exact: true }).click();
  await expect(page.getByRole("button", { name: /Campus baseline validation — completed/ })).toBeVisible();
});

test("real socket reconnect, current membership revocation and UI logout deny old sessions", async ({ page, request, browser }) => {
  // Transport fault injection only: collect real sockets when the application sends subscriptions.
  // No fake messages, HTTP routes, token injection or replacement WebSocket implementation.
  await page.addInitScript(() => {
    const sockets = new Set<WebSocket>();
    const send = WebSocket.prototype.send;
    WebSocket.prototype.send = function (data) { sockets.add(this); return send.call(this, data); };
    Object.assign(window, { r09Disconnect: () => { for (const socket of sockets) socket.close(); sockets.clear(); } });
  });
  let subscribed = 0;
  let denied = 0;
  const socketOrigins = new Set<string>();
  page.on("websocket", (socket) => {
    socketOrigins.add(new URL(socket.url()).origin);
    if (new URL(socket.url()).pathname !== "/ws/topology") return;
    socket.on("framereceived", ({ payload }) => {
      const frame = JSON.parse(String(payload));
      if (frame.event === "subscribed") subscribed++;
      if (frame.event === "error" && frame.data?.code === "WS_INVALID_FILTER") denied++;
    });
  });
  await login(page, "member");
  await selectNetwork(page);
  await expect.poll(() => subscribed).toBeGreaterThan(0);
  // C22: sockets use the same origin as the API (the gateway origin unless overridden), never a baked-in loopback.
  expect([...socketOrigins]).toEqual([origins.ws]);
  const before = subscribed;
  await page.evaluate(() => (window as unknown as { r09Disconnect: () => void }).r09Disconnect());
  await expect.poll(() => subscribed).toBeGreaterThan(before);
  const member = await session(page);

  const adminContext = await browser.newContext({ baseURL: loopback("R09_BASE_URL") });
  try {
    const admin = await adminContext.newPage();
    await login(admin);
    const adminToken = (await session(admin)).accessToken;
    await api(request, adminToken, "DELETE", `/api/v1/organizations/${fixture.owner.org_id}/members/${fixture.users.member.user_id}`, undefined, 204);
    await api(request, member.accessToken, "GET", `/api/v1/networks?workspace_id=${fixture.owner.workspace_id}`, undefined, 403);
    const afterRevocation = subscribed;
    const denial = page.waitForEvent("websocket", { predicate: (ws) => new URL(ws.url()).pathname === "/ws/topology" });
    await page.evaluate(() => (window as unknown as { r09Disconnect: () => void }).r09Disconnect());
    const rejected = await denial;
    await expect.poll(() => rejected.isClosed()).toBe(true);
    await expect.poll(() => denied).toBeGreaterThan(0);
    expect(subscribed).toBe(afterRevocation);
    const logout = pathResponse(admin, "/api/v1/auth/logout", "POST");
    const old = await session(admin);
    await admin.getByRole("button", { name: "Logout", exact: true }).click();
    expect((await logout).status()).toBe(200);
    await expect(admin.getByRole("button", { name: /^Sign In(?:\s*↗)?$/ })).toBeVisible();
    await api(request, old.accessToken, "GET", "/api/v1/auth/me", undefined, 401);
    const refresh = await request.post(`${apiOrigin}/api/v1/auth/refresh`, { data: { refresh_token: old.refreshToken } });
    expect(refresh.status()).toBe(401);
    expect(await admin.evaluate(() => sessionStorage.getItem("nanfo.auth.session"))).toBeNull();
  } finally {
    await adminContext.close();
  }
});

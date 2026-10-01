import { expect, test, type Page, type Route } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test.beforeEach(async ({ page }) => {
  page.on("pageerror", (error) => { throw error; });
});

async function inventoryFixture(page: Page) {
  const state = createDefaultSessionState();
  const original = state.networks[0];
  state.networks = Array.from({ length: 21 }, (_, i) => ({ ...original, network_id: i ? `network-${i + 1}` : original.network_id, name: `Network ${i + 1}` }));
  const device = state.devicesByNetwork[original.network_id][0];
  state.devicesByNetwork[original.network_id] = Array.from({ length: 21 }, (_, i) => ({ ...device, device_id: `device-${i + 1}`, hostname: `router-${i + 1}` }));
  await installSessionMocks(page, state);
  const writes: { method: string; path: string; body: any }[] = [];
  let failure = 0;
  let lostResponse = false;
  const envelope = (data: unknown) => ({ success: true, data, meta: {}, errors: null });
  await page.route("**/api/v1/networks**", async (route) => {
    const req = route.request(); const url = new URL(req.url()); const parts = url.pathname.split("/");
    const networkId = parts[4]; const isDevice = parts[5] === "devices";
    const items = isDevice ? state.devicesByNetwork[networkId] ?? [] : state.networks;
    if (req.method() === "GET") {
      const pageNumber = Number(url.searchParams.get("page") ?? 1); const size = Number(url.searchParams.get("page_size") ?? 20);
      return route.fulfill({ json: envelope({ items: items.slice((pageNumber - 1) * size, pageNumber * size), total: items.length, page: pageNumber, page_size: size }) });
    }
    const body = req.postData() ? req.postDataJSON() : null;
    writes.push({ method: req.method(), path: url.pathname, body });
    if (failure) return route.fulfill({ status: failure, json: { success: false, data: null, meta: {}, errors: { code: `HTTP_${failure}`, message: `Denied ${failure}` } } });
    if (req.method() === "POST") {
      const created = isDevice ? { ...device, ...body, device_id: "created-device", network_id: networkId } : { ...original, ...body, network_id: "created-network" };
      (items as any[]).push(created);
      if (isDevice) state.devicesByNetwork[networkId] = items as typeof state.devicesByNetwork[string];
      if (lostResponse) return route.abort("failed");
      return route.fulfill({ status: 201, json: envelope(created) });
    }
    const id = isDevice ? parts[6] : networkId;
    const index = (items as any[]).findIndex((item) => (isDevice ? item.device_id : item.network_id) === id);
    if (req.method() === "DELETE") { items.splice(index, 1); return route.fulfill({ status: 204 }); }
    Object.assign(items[index], body);
    return route.fulfill({ json: envelope(items[index]) });
  });
  return { state, writes, setFailure: (status: number) => { failure = status; }, loseResponse: () => { lostResponse = true; } };
}

test("21-row inventory pages, exact create payload, edits and confirmed deletions", async ({ page }) => {
  const fixture = await inventoryFixture(page);
  await loginFromUi(page);
  await expect(page.getByRole("navigation", { name: "Networks pagination" })).toContainText("21 total");
  await page.getByRole("navigation", { name: "Networks pagination" }).getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: /21 Network 21/ }).click();
  await page.getByRole("navigation", { name: "Networks pagination" }).getByRole("button", { name: "Previous" }).click();
  await expect(page.getByText("Selected network: Network 21", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Network 21", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /01 Network 1 / }).click();
  await page.getByRole("navigation", { name: "Devices pagination" }).getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Edit router-21", exact: true }).click();
  const edit = page.getByRole("form", { name: "Edit device" });
  await edit.getByLabel("Hostname", { exact: true }).fill("core-router");
  await edit.getByLabel("Spatial reference").fill("");
  await edit.getByRole("button", { name: "Save device" }).click();
  await expect.poll(() => fixture.writes.at(-1)?.body).toEqual({ hostname: "core-router", spatial_ref_id: null });
  await page.getByRole("button", { name: "Delete core-router", exact: true }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByRole("navigation", { name: "Devices pagination" })).toContainText("20 total");
  await page.getByText("Add a device", { exact: true }).click();
  const create = page.getByRole("form", { name: "Create device" });
  await create.getByLabel("Hostname", { exact: true }).fill("operator-ap");
  await create.getByLabel("Device type").fill("access_point");
  await create.getByLabel("IP address").fill("192.0.2.7");
  await create.getByLabel("Vendor").fill("Example");
  await create.getByLabel("Model").fill("AP-1");
  await create.getByLabel("Location hint").fill("West office");
  await create.getByRole("button", { name: "Add Device" }).click();
  await expect.poll(() => fixture.writes.at(-1)?.body).toEqual({ hostname: "operator-ap", device_type: "access_point", ip_address: "192.0.2.7", vendor: "Example", model: "AP-1", location_hint: "West office", spatial_ref_id: null });
  await expect(page.getByText("Selected device: operator-ap (created-device)")).toBeVisible();
  await page.getByText("Create a network", { exact: true }).click();
  const network = page.getByRole("form", { name: "Create network" });
  await network.getByLabel("Network name").fill("Research LAN");
  await network.getByLabel("Network description").fill("Lab devices");
  await network.getByLabel("CIDR").fill("192.0.2.0/24");
  await network.getByRole("button", { name: "Create Network" }).click();
  await expect.poll(() => fixture.writes.at(-1)?.body).toEqual({ workspace_id: fixture.state.workspaceId, name: "Research LAN", description: "Lab devices", cidr: "192.0.2.0/24" });
  await expect(page.getByText("Selected network: Research LAN", { exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "Networks pagination" }).getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Edit Research LAN" }).click();
  await page.getByRole("form", { name: "Edit network" }).getByLabel("Network name").fill("Renamed LAN");
  await page.getByRole("button", { name: "Save network" }).click();
  await page.getByRole("button", { name: "Delete Renamed LAN" }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByText("Selected network: None", { exact: true })).toBeVisible();
});

for (const status of [403, 422, 503]) test(`inventory preserves drafts and shows ${status}`, async ({ page }) => {
  const fixture = await inventoryFixture(page); fixture.setFailure(status);
  await loginFromUi(page);
  await page.getByText("Create a network", { exact: true }).click();
  const form = page.getByRole("form", { name: "Create network" });
  await form.getByLabel("Network name").fill("Retained draft");
  await form.getByRole("button", { name: "Create Network" }).click();
  await expect(form.getByRole("alert")).toContainText(`Denied ${status}`);
  await expect(form.getByLabel("Network name")).toHaveValue("Retained draft");
  if (status === 503) await expect(form.getByRole("button", { name: "Create Network" })).toBeDisabled();
});

test("lost successful create response requires reconciliation before resubmission", async ({ page }) => {
  const fixture = await inventoryFixture(page); fixture.loseResponse();
  await loginFromUi(page);
  await page.getByText("Add a device", { exact: true }).click();
  const form = page.getByRole("form", { name: "Create device" });
  await form.getByLabel("Hostname", { exact: true }).fill("lost-response-router");
  await form.getByLabel("Device type").fill("router");
  await form.getByRole("button", { name: "Add Device" }).click();
  await expect(form.getByRole("alert")).toContainText("Outcome uncertain");
  await expect(form.getByRole("button", { name: "Add Device" })).toBeDisabled();
  await form.getByRole("button", { name: "Refresh records" }).click();
  await page.getByRole("navigation", { name: "Devices pagination" }).getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("button", { name: "Edit lost-response-router" })).toBeVisible();
  expect(fixture.writes).toHaveLength(1);
});

async function tenancyFixture(page: Page, orgRole = "Admin", memberCount = 21) {
  const state = createDefaultSessionState(); await installSessionMocks(page, state);
  const orgs = Array.from({ length: 21 }, (_, i) => ({ org_id: i ? `org-${i + 1}` : state.orgId, name: `Org ${i + 1}`, slug: `org-${i + 1}`, created_at: "2026-09-20" }));
  const workspaces = Array.from({ length: 21 }, (_, i) => ({ org_id: state.orgId, workspace_id: i ? `workspace-${i + 1}` : state.workspaceId, name: `Workspace ${i + 1}`, description: null as string | null, created_at: "2026-09-20" }));
  const members = Array.from({ length: memberCount }, (_, i) => ({ org_id: state.orgId, user_id: i === memberCount - 1 ? state.userId : `user-${i}`, org_role: i === memberCount - 1 ? orgRole : "Read-Only", created_at: "2026-09-20" }));
  const writes: any[] = [];
  const send = (route: Route, data: unknown) => route.fulfill({ json: { success: true, data, meta: {}, errors: null } });
  await page.route("**/api/v1/organizations**", async (route) => {
    const req = route.request(); const url = new URL(req.url()); const parts = url.pathname.split("/");
    const isWorkspace = parts[5] === "workspaces"; const isMember = parts[5] === "members";
    const items: any[] = isWorkspace ? workspaces : isMember ? members : orgs;
    if (req.method() === "GET" && !isWorkspace && !isMember && parts[4]) {
      // C6: GET /organizations/{id} carries the caller's own role.
      const org = orgs.find((item) => item.org_id === parts[4]);
      if (!org) return route.fulfill({ status: 404, json: { success: false, data: null, meta: {}, errors: { code: "ORGANIZATION_NOT_FOUND", message: "Organization not found" } } });
      return send(route, { ...org, caller_role: org.org_id === state.orgId ? orgRole : "Read-Only" });
    }
    if (req.method() === "GET") {
      const p = Number(url.searchParams.get("page") ?? 1); const size = Number(url.searchParams.get("page_size") ?? 20);
      return send(route, { items: items.slice((p - 1) * size, p * size), total: items.length });
    }
    const body = req.postData() ? req.postDataJSON() : {};
    writes.push({ method: req.method(), path: url.pathname, body });
    const key = isWorkspace ? "workspace_id" : isMember ? "user_id" : "org_id";
    const id = isWorkspace || isMember ? parts[6] : parts[4];
    if (req.method() === "POST") { const created = { ...items[0], ...body, [key]: `created-${key}` }; items.push(created); return send(route, created); }
    const index = items.findIndex((item) => item[key] === id);
    if (req.method() === "DELETE") { items.splice(index, 1); return route.fulfill({ status: 204 }); }
    Object.assign(items[index], body); return send(route, items[index]);
  });
  return { state, writes };
}

test("tenancy pages preserve selected scope, gate by current membership, keyboard slug and CRUD", async ({ page }) => {
  const fixture = await tenancyFixture(page, "Admin", 41);
  await loginFromUi(page); await page.getByRole("link", { name: "Tenancy", exact: true }).click();
  await expect(page.getByRole("button", { name: "Create Workspace", exact: true })).toBeEnabled();
  await expect(page.getByRole("navigation", { name: "Members pagination" })).toContainText("41 total · Page 1 of 3");
  await expect(page.getByText(/Locate your.*membership/)).toHaveCount(0);
  await page.getByRole("navigation", { name: "Members pagination" }).getByRole("button", { name: "Next" }).click();
  await page.getByRole("navigation", { name: "Members pagination" }).getByRole("button", { name: "Previous" }).click();
  await expect(page.getByRole("button", { name: "Create Workspace", exact: true })).toBeEnabled();
  await page.getByRole("navigation", { name: "Organizations pagination" }).getByRole("button", { name: "Next" }).click();
  await expect(page.getByLabel("Active Organization")).toHaveValue(fixture.state.orgId);
  await page.getByRole("navigation", { name: "Workspaces pagination" }).getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: /Workspace 21 workspace-21/ }).click();
  await page.getByRole("button", { name: "Edit Workspace 21" }).click();
  const edit = page.getByRole("form", { name: "Edit workspace" });
  await edit.getByLabel("Workspace Name").fill("Final workspace"); await edit.getByRole("button", { name: "Save workspace" }).click();
  await page.getByRole("button", { name: "Delete Final workspace" }).click(); await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByText("Selected workspace: None", { exact: true })).toBeVisible();
  const create = page.getByRole("form", { name: "Create organization" });
  await create.getByLabel("Organization Name").pressSequentially("North Campus");
  await expect(create.getByLabel("Slug", { exact: true })).toHaveValue("north-campus");
  await create.getByLabel("Slug", { exact: true }).fill("north"); await create.getByLabel("Slug", { exact: true }).pressSequentially("-custom");
  await create.getByLabel("Organization Name").fill("Different Name");
  await expect(create.getByLabel("Slug", { exact: true })).toHaveValue("north-custom");
  await create.getByRole("button", { name: "Create Organization" }).click();
  await expect(page.getByLabel("Active Organization")).toHaveValue("created-org_id");
});

test("global writer with org Operator cannot administer tenancy", async ({ page }) => {
  await tenancyFixture(page, "Operator"); await loginFromUi(page); await page.getByRole("link", { name: "Tenancy", exact: true }).click();
  await page.getByRole("navigation", { name: "Members pagination" }).getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("button", { name: "Save organization" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete organization", exact: true })).toBeDisabled();
});

test("organization update/delete and workspace creation clean selected descendant context", async ({ page }) => {
  const fixture = await tenancyFixture(page);
  await loginFromUi(page); await page.getByRole("link", { name: "Tenancy", exact: true }).click();
  await page.getByRole("navigation", { name: "Members pagination" }).getByRole("button", { name: "Next" }).click();
  const org = page.getByRole("form", { name: "Edit organization" });
  await org.getByLabel("Organization name to edit").fill("Renamed organization");
  await org.getByRole("button", { name: "Save organization" }).click();
  await expect.poll(() => fixture.writes.at(-1)?.body).toEqual({ name: "Renamed organization" });
  const workspace = page.getByRole("form", { name: "Create workspace" });
  await workspace.getByLabel("Workspace Name").fill("New workspace");
  await workspace.getByLabel("Description").fill("New description");
  await workspace.getByRole("button", { name: "Create Workspace" }).click();
  await expect(page.getByText("Selected workspace: created-workspace_id", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.sessionStorage.getItem("nanfo.workspace.networkId"))).toBeNull();
  await page.getByRole("button", { name: "Delete organization", exact: true }).click();
  await page.getByRole("button", { name: "Cancel deletion" }).click();
  expect(fixture.writes.some((write) => write.method === "DELETE")).toBe(false);
  await page.getByRole("button", { name: "Delete organization", exact: true }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect.poll(() => page.evaluate(() => ["organizationId", "workspaceId", "networkId"].map((key) => window.sessionStorage.getItem(`nanfo.workspace.${key}`)))).toEqual([null, null, null]);
});

test("inventory pending prevents duplicates, offline preserves draft and network conflict retains selection", async ({ page }) => {
  const fixture = await inventoryFixture(page); await loginFromUi(page);
  let release: (() => void) | undefined;
  await page.route("**/api/v1/networks", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await new Promise<void>((resolve) => { release = resolve; });
    await route.abort("internetdisconnected");
  });
  await page.getByText("Create a network", { exact: true }).click();
  const form = page.getByRole("form", { name: "Create network" });
  await form.getByLabel("Network name").fill("Offline draft");
  await form.getByRole("button", { name: "Create Network" }).click();
  await expect(form.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await expect(form.getByText(/Request pending/)).toBeVisible();
  release?.();
  await expect(form.getByRole("alert")).toContainText("Outcome uncertain");
  await expect(form.getByLabel("Network name")).toHaveValue("Offline draft");
  fixture.setFailure(409);
  await page.getByRole("button", { name: "Delete Network 1", exact: true }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByRole("form", { name: "Delete Network 1" }).getByRole("alert")).toContainText("Denied 409");
  await expect(page.getByText("Selected network: Network 1", { exact: true })).toBeVisible();
});

test("tenancy server denial retains edit draft and current scope", async ({ page }) => {
  const fixture = await tenancyFixture(page); await loginFromUi(page); await page.getByRole("link", { name: "Tenancy", exact: true }).click();
  await expect(page.getByText(`Selected workspace: ${fixture.state.workspaceId}`, { exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "Members pagination" }).getByRole("button", { name: "Next" }).click();
  await page.route(`**/api/v1/organizations/${fixture.state.orgId}`, (route) => route.fulfill({ status: 403, json: { success: false, data: null, meta: {}, errors: { code: "FORBIDDEN", message: "Membership changed" } } }));
  const form = page.getByRole("form", { name: "Edit organization" });
  await form.getByLabel("Organization name to edit").fill("Retained org draft");
  await form.getByRole("button", { name: "Save organization" }).click();
  await expect(form.getByRole("alert")).toContainText("Membership changed");
  await expect(form.getByLabel("Organization name to edit")).toHaveValue("Retained org draft");
  await expect(page.getByLabel("Active Organization")).toHaveValue(fixture.state.orgId);
});

test("member final page removal and re-add use existing scoped membership routes", async ({ page }) => {
  const fixture = await tenancyFixture(page); await loginFromUi(page); await page.getByRole("link", { name: "Tenancy", exact: true }).click();
  await expect(page.getByText(`Selected workspace: ${fixture.state.workspaceId}`, { exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "Members pagination" }).getByRole("button", { name: "Next" }).click();
  const form = page.getByRole("form", { name: "Add member" });
  await form.getByLabel("User ID (UUID)").fill("00000000-0000-0000-0000-000000000999");
  await form.getByLabel("Role", { exact: true }).selectOption("Operator");
  await form.getByRole("button", { name: "Add Member" }).click();
  await expect(page.getByRole("navigation", { name: "Members pagination" })).toContainText("22 total");
  await page.getByRole("button", { name: "Delete member created-user_id", exact: true }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByRole("navigation", { name: "Members pagination" })).toContainText("21 total");
  await form.getByLabel("User ID (UUID)").fill("00000000-0000-0000-0000-000000000999");
  await form.getByRole("button", { name: "Add Member" }).click();
  await expect(page.getByRole("navigation", { name: "Members pagination" })).toContainText("22 total");
  expect(fixture.writes.map((write) => write.method)).toEqual(["POST", "DELETE", "POST"]);
});

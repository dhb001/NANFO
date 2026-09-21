import { expect, test, type WebSocketRoute } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test("rotated session reconciles lifecycle history and paged telemetry on actual socket events/backpressure", async ({ page }) => {
  const state = createDefaultSessionState();
  const network = state.networks[0].network_id;
  const simulation = "00000000-0000-0000-0000-000000000701";
  const device = state.devicesByNetwork[network][0];
  state.devicesByNetwork[network] = Array.from({ length: 41 }, (_, index) => ({ ...device,
    device_id: `00000000-0000-0000-0000-${String(index + 800).padStart(12, "0")}`, hostname: `edge-${index + 1}` }));
  state.simulations = [{ simulation_id: simulation, workspace_id: state.workspaceId, network_id: network,
    scenario_name: "Persisted run", status: "paused", created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z" }];
  await installSessionMocks(page, state);
  await page.route(`**/api/v1/networks/${network}/devices?*`, async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const number = Number(query.get("page"));
    await route.fulfill({ json: { success: true, data: { items: state.devicesByNetwork[network].slice((number - 1) * 20, number * 20), total: 41, page: number, page_size: 20 }, meta: {}, errors: null } });
  });
  await page.route("**/api/v1/telemetry/**", (route) => route.fulfill({ json: { success: true,
    data: route.request().url().endsWith("/health") ? { status: "ok", ingest_lag_ms: null, dropped_events: 0, total_records: 0 }
      : { items: [], total: 0, page: 1, page_size: 120 }, meta: {}, errors: null } }));
  const sockets = new Map<string, WebSocketRoute>();
  await page.routeWebSocket(/\/ws\//, (socket) => socket.onMessage((message) => {
    const request = JSON.parse(String(message));
    sockets.set(request.channel, socket);
    socket.send(JSON.stringify({ event: "subscribed", channel: request.channel, filters: request.filters }));
  }));
  let status = "paused";
  let expire = false;
  const reads: { path: string; authorization: string }[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET" && request.url().includes("/api/v1/")) reads.push({ path: request.url(), authorization: request.headers().authorization });
  });
  await page.route("**/api/v1/auth/refresh", (route) => route.fulfill({ json: { success: true, data: {
    access_token: "rotated-access", refresh_token: "rotated-refresh", token_type: "bearer", expires_in: 900,
  }, meta: {}, errors: null } }));
  await page.route(`**/api/v1/simulations/${simulation}`, async (route) => {
    if (expire) {
      expire = false;
      await route.fulfill({ status: 401, json: { success: false, data: null, meta: {}, errors: { code: "UNAUTHORIZED", message: "Expired" } } });
      return;
    }
    await route.fulfill({ json: { success: true, data: { simulation_id: simulation, workspace_id: state.workspaceId, network_id: network,
      scenario_name: "Persisted run", status, state: status, scenario_id: "scenario", queue_status: "pending", risk_gate: "required", validation: {}, run_output: {}, updated_at: "2026-09-20T10:01:00Z" }, meta: {}, errors: null } });
  });
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: /^Simulation/ }).click();
  await page.getByRole("button", { name: "Persisted run — paused" }).click();
  await page.getByLabel("Scenario Name", { exact: true }).fill("Keep my draft");
  expire = true;
  await page.getByRole("button", { name: "Refresh simulation status" }).click();
  await expect.poll(() => sockets.get("digital-twin")?.url()).toContain("rotated-access");
  await expect(page.getByLabel("Scenario Name", { exact: true })).toHaveValue("Keep my draft");
  await expect(page.getByLabel("Simulation ID", { exact: true })).toHaveValue(simulation);
  status = "cancelled";
  state.simulations[0].status = status;
  const before = reads.length;
  sockets.get("digital-twin")!.send(JSON.stringify({ event: "simulation.cancelled", timestamp: "2026-09-20T10:01:00Z", data: {
    delta_type: "update", scene_object: { id: `simulation:${simulation}`, object_type: "simulation_state", simulation_id: simulation, status },
  } }));
  await expect(page.getByRole("button", { name: "Persisted run — cancelled" })).toBeVisible();
  expect(reads.slice(before).filter((read) => read.path.includes("/simulations")).every((read) => read.authorization === "Bearer rotated-access")).toBe(true);

  await page.getByRole("link", { name: /^Telemetry/ }).click();
  await page.getByRole("button", { name: "Next devices", exact: true }).click();
  await expect(page.getByText("Page 2 | 41 devices", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Next devices", exact: true }).click();
  await page.getByLabel("Telemetry device", { exact: true }).selectOption(state.devicesByNetwork[network][40].device_id);
  await expect(page.getByText("Page 3 | 41 devices", { exact: false })).toBeVisible();
  const recoveryStart = reads.length;
  for (const channel of ["topology", "telemetry"]) sockets.get(channel)!.send(JSON.stringify({ event: "error", data: { code: "WS_BACKPRESSURE", message: "Dropped delta" } }));
  await expect.poll(() => reads.slice(recoveryStart).some((read) => read.path.includes("/devices?") && new URL(read.path).searchParams.get("page") === "3")).toBe(true);
  await expect.poll(() => reads.slice(recoveryStart).some((read) => read.path.includes(`/telemetry/device/${state.devicesByNetwork[network][40].device_id}`))).toBe(true);
  await expect.poll(() => reads.slice(recoveryStart).some((read) => read.path.includes("/telemetry/history?"))).toBe(true);
  expect(reads.slice(recoveryStart).every((read) => read.authorization === "Bearer rotated-access")).toBe(true);
  await expect(page.getByLabel("Telemetry device", { exact: true })).toHaveValue(state.devicesByNetwork[network][40].device_id);
});

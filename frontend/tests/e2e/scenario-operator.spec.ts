import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

for (const override of [false, true]) test(`configured scenario ${override ? "changed-input branch" : "identical checkpoint branch"} on mobile (contract fixtures, not physics validation)`, async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  const original = "00000000-0000-0000-0000-000000000701";
  const branch = "00000000-0000-0000-0000-000000000702";
  const states: Record<string, string> = {};
  const inputs: Record<string, unknown>[] = [];
  const requests: { route: string; body: Record<string, unknown> }[] = [];
  let config: Record<string, unknown> = {};
  const configs: Record<string, Record<string, unknown>> = {};
  const metrics = { latency_ms: 200, loss_pct: 2, throughput_mbps: 5 };
  await page.route("**/api/v1/simulations/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      requests.push({ route: path, body });
      let id = original;
      if (path.endsWith("/start")) {
        if (body.simulation_id) { id = body.simulation_id; states[id] = "queued"; }
        else { config = body.scenario_config; configs[id] = config; inputs.push(config); states[id] = "queued"; }
      } else if (path.endsWith("/pause")) { id = body.simulation_id; states[id] = "paused"; }
      else { id = branch; states[id] = "draft"; configs[id] = body.scenario_config ?? configs[original]; }
      await route.fulfill({ json: { success: true, data: { simulation_id: id, status: states[id], validation: { source: "operator_configured_model", physical_safety_authorized: false } }, meta: {}, errors: null } });
      return;
    }
    if (path.includes("/compare/")) {
      const candidate = path.split("/").at(-3)!;
      const baseline = path.split("/").at(-1)!;
      const compatible = states[candidate] === "completed" && states[baseline] === "completed";
      await route.fulfill({ json: { success: true, data: { simulation_id: candidate, baseline_simulation_id: baseline, compatible,
        comparison_reason: compatible ? null : "completed_common_modeled_workload_required", deltas: compatible ? override && candidate !== baseline ? { latency_ms: -10, loss_pct: -1, throughput_mbps: 1 } : { latency_ms: 0, loss_pct: 0, throughput_mbps: 0 } : { latency_ms: null, loss_pct: null, throughput_mbps: null } }, meta: {}, errors: null } });
      return;
    }
    const id = path.split("/").at(-1)!;
    const changed = override && id === branch;
    const outputMetrics = changed ? { latency_ms: 190, loss_pct: 1, throughput_mbps: 6 } : metrics;
    await route.fulfill({ json: { success: true, data: { simulation_id: id, network_id: "00000000-0000-0000-0000-000000000333", scenario_name: "Configured fixture", scenario_id: "scenario", status: states[id], risk_gate: "blocked", queue_status: "pending", validation: {}, scenario_config: configs[id],
      audit_provenance: { checkpoint_copied: id === branch && !changed, input_override_restarted: changed },
      evidence_expires_at: "2020-01-01T00:00:00Z", run_output: { ...outputMetrics, model_version: "finite-buffer-fluid.v1", source: "operator_configured_model", physical_safety_authorized: false,
        input_sha256: (changed ? "e" : "a").repeat(64), checkpoint_sha256: (changed ? "f" : "b").repeat(64), output_sha256: (changed ? "1" : "c").repeat(64), workload_sha256: "d".repeat(64), elapsed_ms: 10000,
        trace: [{ elapsed_ms: 100, flows: { offered: { ...outputMetrics, latency_ms: null } } }, { elapsed_ms: 200, flows: { offered: outputMetrics } }] } }, meta: {}, errors: null } });
  });
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: /^Simulation/ }).click();
  await expect(page.getByText(/Explicit operator example, not live topology/)).toBeVisible();
  await page.getByRole("button", { name: "Start Simulation", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeEnabled();
  expect(inputs[0]).toMatchObject({ version: 1, seed: 42, tick_ms: 100, duration_ticks: 100, action_binding: null });
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resume / start draft" })).toBeEnabled();
  await page.getByRole("button", { name: "Resume / start draft" }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeEnabled();
  expect(requests[2].body).toMatchObject({ simulation_id: original });
  expect(requests[2].body).not.toHaveProperty("scenario_config");
  states[original] = "completed";
  await page.getByRole("button", { name: "Refresh simulation status" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();
  if (override) {
    await page.getByLabel("egress capacity_mbps", { exact: true }).fill("12");
    await page.getByLabel(/Branch with editor inputs/).check();
  }
  await page.getByRole("button", { name: "Branch", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resume / start draft" })).toBeEnabled();
  expect(requests.at(-1)?.body).toMatchObject({ parent_simulation_id: original });
  if (override) {
    expect(requests.at(-1)?.body.scenario_config).not.toEqual(configs[original]);
    expect(configs[branch].links).toEqual(expect.arrayContaining([expect.objectContaining({ link_id: "egress", capacity_mbps: 12 })]));
  } else expect(requests.at(-1)?.body).not.toHaveProperty("scenario_config");
  await page.getByRole("button", { name: "Resume / start draft" }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeEnabled();
  expect(requests.at(-1)?.body.simulation_id).toBe(branch);
  states[branch] = "completed";
  await page.getByRole("button", { name: "Refresh simulation status" }).click();
  await page.getByRole("button", { name: "Refresh comparison" }).click();
  await expect(page.getByText(override ? "-10 ms" : "0 ms", { exact: true })).toBeVisible();
  await expect(page.getByText(override ? "-1 %" : "0 %", { exact: true })).toBeVisible();
  await expect(page.getByText(override ? "1 Mbps" : "0 Mbps", { exact: true })).toBeVisible();
  await expect(page.getByText(/Lifecycle handoff source: operator_configured_model/)).toContainText("false (not authorized)");
  await expect(page.getByText("Modeled goodput", { exact: true })).toBeVisible();
  await expect(page.getByText(/Modeled evidence expiry: Expired/)).toBeVisible();
  await page.getByLabel("Comparison metric", { exact: true }).selectOption("throughput_mbps");
  await page.setViewportSize({ width: 390, height: 844 });
  const summary = page.getByText("Modeled comparison history data table", { exact: true });
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("table").last()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.route("**/api/v1/telemetry/history**", async (route) => route.fulfill({ json: { success: true, data: { items: [
    { record_id: "sample", device_id: "switch", metric: "latency_ms", value: 12, unit: "ms", source: "emulation", observed_at: "2026-09-10T00:00:00Z", tags: { synthetic: false, execution_mode: "emulation", port_no: 1, peer_host: "h2", run_id: "measured-run" } },
  ], total: 1, page: 1, page_size: 120 }, meta: {}, errors: null } }));
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("link", { name: /^Telemetry/ }).click();
  await expect(page.getByRole("img", { name: /Telemetry time series/ })).toBeVisible();
  await expect(page.getByText("Measured emulation", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Fetched 1 records on this page/)).toBeVisible();
});

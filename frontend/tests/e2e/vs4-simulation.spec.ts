import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS4 simulation", () => {
  test("start + detail + compare simulation workflow", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/simulations/start", async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000701",
            resumed_from_simulation_id: null,
            scenario_id: "scenario-701",
            network_id: "00000000-0000-0000-0000-000000000333",
            scene_object_id: "simulation-state",
            state: "queued",
            status: "queued",
            risk_gate: "required",
            scenario_name: "Campus baseline validation",
            validation: {
              pipeline_stage: "queued",
              required_checks: ["simulation_before_deployment"],
              policy_reference: "ADR-008",
              status: "queued",
              queued_at: "2026-08-13T11:00:00Z",
              requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            },
            requested_at: "2026-08-13T11:00:00Z",
            correlation_id: "corr-sim-start",
            queue_status: "queued",
            stream_entry_id: "100",
            warning: null,
          },
          meta: { request_id: "req-sim-start", timestamp: "2026-08-13T11:00:00Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/simulations/00000000-0000-0000-0000-000000000701", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000701",
            parent_simulation_id: null,
            scenario_id: "scenario-701",
            network_id: "00000000-0000-0000-0000-000000000333",
            workspace_id: "00000000-0000-0000-0000-000000000222",
            scene_object_id: "simulation-state",
            state: "running",
            status: "running",
            risk_gate: "required",
            scenario_name: "Campus baseline validation",
            validation: { pipeline_stage: "running" },
            run_output: { latency_ms: 15.2, loss_pct: 0.2, throughput_mbps: 1000 },
            model_versions: {},
            audit_provenance: {},
            queue_status: "queued",
            stream_entry_id: "100",
            warning: null,
            requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            requested_at: "2026-08-13T11:00:00Z",
            created_at: "2026-08-13T11:00:00Z",
            updated_at: "2026-08-13T11:00:10Z",
          },
          meta: { request_id: "req-sim-detail", timestamp: "2026-08-13T11:00:10Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/simulations/00000000-0000-0000-0000-000000000701/compare/00000000-0000-0000-0000-000000000701", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000701",
            baseline_simulation_id: "00000000-0000-0000-0000-000000000701",
            scenario_id: "scenario-701",
            baseline_scenario_id: "scenario-701",
            network_id: "00000000-0000-0000-0000-000000000333",
            simulation_metrics: { latency_ms: 15.2, loss_pct: 0.2, throughput_mbps: 1000 },
            baseline_metrics: { latency_ms: 15.2, loss_pct: 0.2, throughput_mbps: 1000 },
            deltas: { latency_ms: 0, loss_pct: 0, throughput_mbps: 0 },
          },
          meta: { request_id: "req-sim-compare", timestamp: "2026-08-13T11:00:11Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Simulation" }).click();
    await expect(page).toHaveURL(/\/ops\/simulation$/);

    await page.getByRole("button", { name: "Start Simulation" }).click();
    await expect(page.getByText("Simulation Detail")).toBeVisible();
    await expect(page.getByText("simulation_id: 00000000-0000-0000-0000-000000000701")).toBeVisible();
    await expect(page.getByText("Latency delta")).toBeVisible();
  });
});

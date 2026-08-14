import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS7 branch and compare", () => {
  test("branches simulation and displays compare deltas", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/simulations/start", async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000801",
            resumed_from_simulation_id: null,
            scenario_id: "scenario-801",
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
              queued_at: "2026-08-13T12:00:00Z",
              requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            },
            requested_at: "2026-08-13T12:00:00Z",
            correlation_id: "corr-vs7-start",
            queue_status: "queued",
            stream_entry_id: "300",
            warning: null,
          },
          meta: { request_id: "req-vs7-start", timestamp: "2026-08-13T12:00:00Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/simulations/branch", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000802",
            parent_simulation_id: "00000000-0000-0000-0000-000000000801",
            scenario_id: "scenario-802",
            network_id: "00000000-0000-0000-0000-000000000333",
            scene_object_id: "simulation-state",
            state: "draft",
            status: "draft",
            risk_gate: "required",
            scenario_name: "Branch candidate",
            validation: {
              pipeline_stage: "branch_draft",
              required_checks: ["simulation_before_deployment"],
              policy_reference: "ADR-008",
              status: "draft",
              queued_at: "2026-08-13T12:00:10Z",
              requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            },
            requested_at: "2026-08-13T12:00:10Z",
            correlation_id: "corr-vs7-branch",
          },
          meta: { request_id: "req-vs7-branch", timestamp: "2026-08-13T12:00:10Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/simulations/00000000-0000-0000-0000-000000000802", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000802",
            parent_simulation_id: "00000000-0000-0000-0000-000000000801",
            scenario_id: "scenario-802",
            network_id: "00000000-0000-0000-0000-000000000333",
            workspace_id: "00000000-0000-0000-0000-000000000222",
            scene_object_id: "simulation-state",
            state: "draft",
            status: "draft",
            risk_gate: "required",
            scenario_name: "Branch candidate",
            validation: { pipeline_stage: "branch_draft" },
            run_output: { latency_ms: 20.2, loss_pct: 0.6, throughput_mbps: 960 },
            model_versions: {},
            audit_provenance: {},
            queue_status: "draft",
            stream_entry_id: null,
            warning: null,
            requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            requested_at: "2026-08-13T12:00:10Z",
            created_at: "2026-08-13T12:00:10Z",
            updated_at: "2026-08-13T12:00:11Z",
          },
          meta: { request_id: "req-vs7-detail", timestamp: "2026-08-13T12:00:11Z" },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/simulations/00000000-0000-0000-0000-000000000802/compare/00000000-0000-0000-0000-000000000801", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            simulation_id: "00000000-0000-0000-0000-000000000802",
            baseline_simulation_id: "00000000-0000-0000-0000-000000000801",
            scenario_id: "scenario-802",
            baseline_scenario_id: "scenario-801",
            network_id: "00000000-0000-0000-0000-000000000333",
            simulation_metrics: { latency_ms: 20.2, loss_pct: 0.6, throughput_mbps: 960 },
            baseline_metrics: { latency_ms: 15.2, loss_pct: 0.2, throughput_mbps: 1000 },
            deltas: { latency_ms: 5, loss_pct: 0.4, throughput_mbps: -40 },
          },
          meta: { request_id: "req-vs7-compare", timestamp: "2026-08-13T12:00:12Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await expect(page.getByRole("heading", { name: "Networks" })).toBeVisible();
    await page.getByRole("button", { name: /Network A/ }).click();

    await page.getByRole("link", { name: "Simulation" }).click();
    await expect(page.getByRole("button", { name: "Start Simulation" })).toBeEnabled();
    await page.getByRole("button", { name: "Start Simulation" }).click();
    await page.getByRole("button", { name: "Branch" }).click();

    await expect(page.getByRole("heading", { name: "Compare" })).toBeVisible();
    await expect(page.getByText(/5\s*ms/)).toBeVisible();
    await expect(page.getByText(/0\.4\s*%/)).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";

test.describe("VS8 intent parity", () => {
  test("validate -> execute -> realtime status transition with retry path", async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);

    await page.route("**/api/v1/intents/validate", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            intent_id: "00000000-0000-0000-0000-000000000901",
            workspace_id: "00000000-0000-0000-0000-000000000222",
            network_id: "00000000-0000-0000-0000-000000000333",
            status: "validated",
            intent_kind: "reroute_path",
            validation: {
              is_valid: true,
              reasons: [],
              required_checks: ["simulation_before_deployment"],
              capability_match: "supported",
              dependency_analysis: "ok",
              simulation_required: true,
              policy_reference: "ADR-008",
              validated_at: "2026-08-13T10:00:10Z",
            },
            explainability: {
              summary: "Ready",
              evidence: [],
              alternatives_considered: [],
              policy_reference: "ADR-008",
            },
            confidence: {
              score: 0.84,
              band: "high",
              approval_required: false,
            },
            idempotency_key: "intent-test",
            correlation_id: "corr-1",
            requested_at: "2026-08-13T10:00:10Z",
            queue_status: "queued",
            stream_entry_id: "111",
            warning: null,
          },
          meta: { request_id: "req-intent-validate", timestamp: "2026-08-13T10:00:10Z" },
          errors: null,
        }),
      });
    });

    let executeAttempts = 0;
    await page.route("**/api/v1/intents/execute", async (route) => {
      executeAttempts += 1;
      if (executeAttempts === 1) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-intent-exec-1", timestamp: "2026-08-13T10:00:11Z" },
            errors: {
              code: "INTENT_IDEMPOTENCY_CONFLICT",
              message: "idempotency_key is already bound to a different intent.",
            },
          }),
        });
        return;
      }

      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            intent_id: "00000000-0000-0000-0000-000000000901",
            workspace_id: "00000000-0000-0000-0000-000000000222",
            network_id: "00000000-0000-0000-0000-000000000333",
            status: "execution_started",
            intent_kind: "reroute_path",
            queue_status: "queued",
            stream_entry_id: "112",
            warning: null,
            validation_result: { validated_at: "2026-08-13T10:00:10Z" },
            execution_provenance: { execution_started_at: "2026-08-13T10:00:12Z" },
            explainability: { summary: "Execution started" },
            confidence: { score: 0.84, band: "high", approval_required: false },
            idempotency_key: "intent-test-2",
            correlation_id: "corr-2",
            requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            requested_at: "2026-08-13T10:00:12Z",
            updated_at: "2026-08-13T10:00:12Z",
            idempotent_replay: false,
          },
          meta: { request_id: "req-intent-exec-2", timestamp: "2026-08-13T10:00:12Z" },
          errors: null,
        }),
      });
    });

    let detailCall = 0;
    await page.route("**/api/v1/intents/00000000-0000-0000-0000-000000000901?workspace_id=00000000-0000-0000-0000-000000000222", async (route) => {
      detailCall += 1;
      const status = detailCall >= 2 ? "execution_failed" : "execution_started";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            intent_id: "00000000-0000-0000-0000-000000000901",
            workspace_id: "00000000-0000-0000-0000-000000000222",
            network_id: "00000000-0000-0000-0000-000000000333",
            status,
            intent_kind: "reroute_path",
            intent_payload: { action: "reroute_path" },
            validation_result: { validated_at: "2026-08-13T10:00:10Z" },
            execution_provenance: {
              execution_started_at: "2026-08-13T10:00:12Z",
              execution_failed_at: "2026-08-13T10:00:20Z",
              failure_reason: "post_change_verification_failed",
              verification: {
                status: "failed",
              },
              rollback: {
                attempted: true,
                status: "completed",
                rollback_reference_id: "rbk-1",
              },
            },
            explainability: { summary: "Execution failed verification; rollback baseline completed." },
            confidence: { score: 0.84, band: "high", approval_required: false },
            idempotency_key: "intent-test-2",
            queue_status: "deferred",
            stream_entry_id: "112",
            warning: "event_queue_unavailable",
            correlation_id: "corr-2",
            requested_by_user_id: "00000000-0000-0000-0000-000000000123",
            requested_at: "2026-08-13T10:00:10Z",
            created_at: "2026-08-13T10:00:10Z",
            updated_at: "2026-08-13T10:00:20Z",
          },
          meta: { request_id: "req-intent-detail", timestamp: "2026-08-13T10:00:13Z" },
          errors: null,
        }),
      });
    });

    await loginFromUi(page);

    await page.getByRole("link", { name: "Intent" }).click();
    await expect(page).toHaveURL(/\/ops\/intent$/);
    await page.getByLabel("Idempotency Key").fill("intent-test");
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByText("Intent validated")).toBeVisible();

    await page.getByRole("button", { name: "Execute" }).click();
    await expect(page.getByText("Idempotency conflict")).toBeVisible();

    await page.getByLabel("Idempotency Key").fill("intent-test-2");
    await page.getByRole("button", { name: "Execute" }).click();
    await expect(page.getByText("Execution request received")).toBeVisible();

    await expect(page.getByText("execution_failed").first()).toBeVisible();
    await expect(page.getByText("rollback_ref: rbk-1")).toBeVisible();
  });
});

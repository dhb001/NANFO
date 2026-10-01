import { expect, test } from "@playwright/test";
import {
  createDefaultSessionState,
  installSessionMocks,
  loginFromUi,
} from "./support/session";
import { errorEnvelope, executeResponse, intentDetail, labApprovalBinding, okEnvelope, validateResponse } from "./support/contracts";

const INTENT_ID = "00000000-0000-0000-0000-000000000901";

test.describe("VS8 intent parity (ADR-028 C3 contract)", () => {
  test("validate with a fresh key -> execute with the stored key and current approval binding -> binding mismatch re-read", async ({ page }) => {
    const state = createDefaultSessionState();
    const networkId = state.networks[0].network_id;
    await installSessionMocks(page, state);
    const validateKeys: string[] = [];
    const executeBodies: Record<string, unknown>[] = [];
    const executeKeys: (string | undefined)[] = [];
    let storedKey: string | null = null;
    let binding = labApprovalBinding;
    const rotatedBinding = { ...labApprovalBinding, run_id: "00000000-0000-0000-0000-0000000000bb" };

    await page.route("**/api/v1/intents/validate", async (route) => {
      const key = route.request().headers()["idempotency-key"];
      validateKeys.push(key);
      storedKey = key;
      await route.fulfill({ status: 200, json: okEnvelope(validateResponse({
        intent_id: INTENT_ID, workspace_id: state.workspaceId, network_id: networkId, idempotency_key: key,
        validation: {
          is_valid: true, reasons: [], required_checks: ["simulation_before_deployment"], capability_match: "trusted_lab_plan",
          dependency_analysis: "not_performed", simulation_required: false, policy_reference: "ADR-010", validated_at: "2026-08-13T10:00:10Z",
          validation_kind: "manual_lab_plan", model_evidence: "unavailable",
        },
        approval_binding: binding,
      })) });
    });

    await page.route("**/api/v1/intents/execute", async (route) => {
      executeBodies.push(route.request().postDataJSON());
      executeKeys.push(route.request().headers()["idempotency-key"]);
      if (executeBodies.length === 1) {
        // The lab run was replaced after approval: the server refuses and nothing runs.
        binding = rotatedBinding;
        await route.fulfill({ status: 409, json: errorEnvelope("APPROVAL_BINDING_MISMATCH",
          "approval_binding must equal the current plan_hash, binding_digest and run_id; refresh the intent detail and approve the current lab identity.") });
        return;
      }
      await route.fulfill({ status: 202, json: okEnvelope(executeResponse({
        intent_id: INTENT_ID, workspace_id: state.workspaceId, network_id: networkId, idempotency_key: storedKey,
        execution_provenance: { execution_started_at: "2026-08-13T10:00:12Z" }, approval_binding: binding,
      })) });
    });

    await page.route(`**/api/v1/intents/${INTENT_ID}?workspace_id=${state.workspaceId}`, async (route) => {
      const failed = executeBodies.length >= 2;
      await route.fulfill({ status: 200, json: okEnvelope(intentDetail({
        intent_id: INTENT_ID, workspace_id: state.workspaceId, network_id: networkId,
        status: failed ? "execution_failed" : "validated", intent_payload: { action: "reroute_path" },
        validation_result: { validated_at: "2026-08-13T10:00:10Z", validation_kind: "manual_lab_plan", model_evidence: "unavailable", simulation_required: false },
        execution_provenance: failed ? {
          execution_started_at: "2026-08-13T10:00:12Z", execution_failed_at: "2026-08-13T10:00:20Z", failure_reason: "post_change_verification_failed",
          verification: { status: "failed" }, rollback: { attempted: true, status: "completed", rollback_reference_id: "rbk-1" },
        } : {},
        explainability: { summary: failed ? "Execution failed verification; rollback baseline completed." : "Ready" },
        idempotency_key: storedKey, queue_status: failed ? "outbox_pending" : "queued", approval_binding: binding,
      })) });
    });

    await loginFromUi(page);
    await page.getByRole("link", { name: "Intent" }).click();
    await expect(page).toHaveURL(/\/ops\/intent$/);
    await page.getByRole("button", { name: "Validate", exact: true }).click();
    await expect(page.getByText("Intent validated")).toBeVisible();
    expect(validateKeys).toHaveLength(1);
    expect(validateKeys[0]).toMatch(/^intent-[0-9a-f-]{36}$/);
    await expect(page.getByLabel("Execution idempotency key")).toHaveValue(validateKeys[0]);
    await expect(page.getByText(`run_id: ${labApprovalBinding.run_id}`)).toBeVisible();

    await expect(page.getByRole("button", { name: "Execute", exact: true })).toBeDisabled();
    await page.getByRole("checkbox", { name: /explicitly approve/ }).check();
    await page.getByRole("button", { name: "Execute", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "APPROVAL_BINDING_MISMATCH" })).toContainText("Lab identity changed since approval");
    // The detail was re-read and approval revoked: the operator approves the current identity explicitly.
    await expect(page.getByText(`run_id: ${rotatedBinding.run_id}`)).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();

    await page.getByRole("checkbox", { name: /explicitly approve/ }).check();
    await page.getByRole("button", { name: "Execute", exact: true }).click();
    await expect(page.getByText("Execution request received")).toBeVisible();
    expect(executeBodies[0]).toMatchObject({ intent_id: INTENT_ID, idempotency_key: validateKeys[0], manual_approval: true, cancel: false, approval_binding: labApprovalBinding });
    expect(executeBodies[1]).toMatchObject({ idempotency_key: validateKeys[0], approval_binding: rotatedBinding });
    expect(executeKeys).toEqual([validateKeys[0], validateKeys[0]]);

    await expect(page.getByText("execution_failed").first()).toBeVisible();
    await expect(page.getByText("rollback_ref: rbk-1")).toBeVisible();

    // A new submission always gets a new validation key.
    await page.getByRole("button", { name: "Validate", exact: true }).click();
    await expect.poll(() => validateKeys.length).toBe(2);
    expect(validateKeys[1]).not.toBe(validateKeys[0]);
  });
});

import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test("manual approval, lost response replay, cancellation and uncertain readback on a narrow viewport", async ({ page }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  let status = "validated";
  let terminal = false;
  const requests: Record<string, unknown>[] = [];
  const envelope = (data: unknown) => ({ success: true, data, meta: { request_id: "manual-lab", timestamp: "2026-09-09T12:00:00Z", execution_mode: "emulation" }, errors: null });
  await page.route("**/api/v1/intents/lab-intent?*", async (route) => {
    await route.fulfill({ json: envelope({
      intent_id: "lab-intent", workspace_id: state.workspaceId, status,
      intent_payload: { action: "throttle_qos", scope: { source_host: "h1", destination_host: "h2" }, constraints: { operation: "police", rate_mbps: 10 } },
      validation_result: {}, explainability: {}, confidence: { score: 0, band: "unavailable", approval_required: true },
      idempotency_key: "manual-lab-key", queue_status: "queued",
      execution_provenance: terminal ? { execution_id: "job-1", phase: "uncertain", verification: { status: "uncertain" }, rollback: { status: "failed" }, failure_reason: "readback_unavailable" } : {},
    }) });
  });
  await page.route("**/api/v1/intents/execute", async (route) => {
    const request = route.request().postDataJSON();
    requests.push(request);
    expect(route.request().headers()["idempotency-key"]).toBe("manual-lab-key");
    if (requests.length === 1) {
      await route.abort("connectionreset");
      return;
    }
    status = "execution_started";
    if (request.cancel) {
      terminal = true;
      status = "execution_failed";
    }
    await route.fulfill({ status: 202, json: envelope({ status: "execution_started", queue_status: "queued", execution_provenance: { execution_id: "job-1" } }) });
  });
  await loginFromUi(page);
  await page.getByRole("link", { name: "Intent" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Intent ID", { exact: true }).fill("lab-intent");
  await page.getByLabel("Idempotency Key").fill("manual-lab-key");
  await expect(page.getByRole("checkbox", { name: /explicitly approve/ })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Execute", exact: true })).toBeDisabled();
  expect(requests).toHaveLength(0);
  await page.getByRole("checkbox", { name: /explicitly approve/ }).check();
  await page.getByRole("button", { name: "Execute", exact: true }).click();
  await expect(page.getByText(/Request outcome unknown/)).toBeVisible();
  await page.getByRole("button", { name: "Execute", exact: true }).click();
  await expect(page.getByText(/Execution accepted, not completed/)).toBeVisible();
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0]).toMatchObject({ manual_approval: true, cancel: false });
  await page.getByRole("button", { name: "Cancel execution" }).click();
  expect(requests[2]).toEqual({ ...requests[0], cancel: true });
  await expect(page.getByText("Execution outcome uncertain")).toBeVisible();
  await expect(page.getByText("Execution Completed", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel execution" })).toBeDisabled();
});

test("completed policy cancellation reconciles to verified rollback; safe failures report no mutation", async ({ page }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  let cancelled = false;
  const requests: Record<string, unknown>[] = [];
  const envelope = (data: unknown) => ({ success: true, data, meta: { request_id: "compensate", timestamp: "2026-09-09T12:00:00Z", execution_mode: "emulation" }, errors: null });
  await page.route("**/api/v1/intents/*?*", async (route) => {
    const safeFailure = route.request().url().includes("safe-failure?");
    await route.fulfill({ json: envelope({
      intent_id: safeFailure ? "safe-failure" : "completed-policy", workspace_id: state.workspaceId,
      status: cancelled || safeFailure ? "execution_failed" : "execution_completed",
      intent_payload: { action: "throttle_qos", constraints: { operation: "police" } },
      validation_result: {}, explainability: {}, confidence: { score: 0, band: "unavailable", approval_required: true },
      idempotency_key: "persisted-key", queue_status: "outbox_pending",
      execution_provenance: safeFailure ? { phase: "failed", verification: { no_mutation_verified: true }, rollback: null, failure_reason: "deadline_before_dispatch" }
        : cancelled ? { execution_id: "job-1", phase: "cancelled", rollback: { verified: true, readback_sha256: "b".repeat(64) } }
          : { execution_id: "job-1", phase: "completed", verification: { readback_verified: true, readback_sha256: "a".repeat(64), probe: { sent: 3, received: 3 } } },
    }) });
  });
  await page.route("**/api/v1/intents/execute", async (route) => {
    requests.push(route.request().postDataJSON());
    expect(route.request().headers()["idempotency-key"]).toBe("persisted-key");
    cancelled = true;
    await route.fulfill({ status: 202, json: envelope({ status: "execution_started", queue_status: "outbox_pending" }) });
  });
  await loginFromUi(page);
  await page.getByRole("link", { name: "Intent" }).click();
  await page.getByLabel("Intent ID", { exact: true }).fill("completed-policy");
  await expect(page.getByText("verification readback verified")).toBeVisible();
  await expect(page.getByText("completion_scope: config_readback_and_reachability")).toBeVisible();
  await expect(page.getByText("Reachability probe: 3/3 received")).toBeVisible();
  await expect(page.getByRole("button", { name: "Execute", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Cancel execution" }).click();
  expect(requests).toEqual([{ workspace_id: state.workspaceId, intent_id: "completed-policy", idempotency_key: "persisted-key", manual_approval: false, cancel: true }]);
  await expect(page.getByText("rollback verified")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel execution" })).toBeDisabled();
  await page.getByLabel("Intent ID", { exact: true }).fill("safe-failure");
  await expect(page.getByText(/No mutation verified by the backend/)).toBeVisible();
  await expect(page.getByText("completion_scope: Not reported")).toBeVisible();
  await expect(page.getByText("rollback verified")).toHaveCount(0);
  await expect(page.getByText("Execution Completed", { exact: true })).toHaveCount(0);
});

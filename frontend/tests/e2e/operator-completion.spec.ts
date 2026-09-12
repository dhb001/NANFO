import { expect, test } from "@playwright/test";
import { autonomyFixture } from "../../src/features/autonomy/fixtures";
import { configurationFixture, modelFixture, modelRecordFixture, overrideFixture, overrideIntentFixture } from "../../src/features/autonomy/operatorFixtures";
import { pathsFixture } from "../../src/features/telemetry/pathFixtures";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

const envelope = (data: unknown) => ({ success: true, data, meta: { execution_mode: "emulation" }, errors: null });
test("ADR018 mobile keyboard panels preserve server outcomes, immutable training and selected probe scope", async ({ page }) => {
  const session = createDefaultSessionState(); await installSessionMocks(page, session);
  let control = autonomyFixture(); let config = configurationFixture(); const model = modelFixture();
  let rows: ReturnType<typeof overrideFixture>[] = []; let pathData = pathsFixture();
  const writes: { path: string; body: unknown }[] = [];
  await page.route("**/api/v1/autonomy**", async (route) => {
    const request = route.request(); const url = new URL(request.url());
    if (request.method() === "GET") {
      expect(url.searchParams.get("network_id")).toBe(control.network_id);
      const data = url.pathname.endsWith("/model") ? model : url.pathname.endsWith("/configuration") ? config : url.pathname.endsWith("/overrides")
        ? { network_id: control.network_id, control_revision: control.revision, overrides: rows, history_limit: 100 } : control;
      await route.fulfill({ json: envelope(data) }); return;
    }
    const body = request.postData() ? request.postDataJSON() : null;
    writes.push({ path: url.pathname, body });
    if (url.pathname.endsWith("/model/diagnose")) {
      expect(body).toEqual({ network_id: control.network_id, history_reference: "measured-history-1" });
      await route.fulfill({ status: 201, json: envelope(modelRecordFixture()) }); return;
    }
    if (url.pathname.endsWith("/configuration")) {
      expect(body.expected_revision).toBe(config.revision); expect(body.reason).toBe("Requested reward revision");
      expect(body.training.reward_weights).toEqual({ goodput: 2 });
      const version = { revision: config.revision + 1, actor_id: session.userId, reason: body.reason, operational: body.operational,
        training: body.training, content_sha256: "b".repeat(64), created_at: new Date().toISOString() };
      config = { ...config, revision: version.revision, operational: body.operational, requested_training: body.training, history: [version, ...config.history] };
      control = { ...control, revision: control.revision + 1 };
      await route.fulfill({ json: envelope(config) }); return;
    }
    if (url.pathname.endsWith("/overrides")) {
      expect(body).toMatchObject({ network_id: control.network_id, intent_id: overrideFixture().intent_id, execution_id: overrideFixture().execution_id,
        expected_revision: control.revision, duration_seconds: 300, reason: "Temporary maintenance", return_mode: "monitor" });
      rows = [overrideFixture({ expires_at: new Date(Date.now() + 300_000).toISOString() })];
      control = { ...control, revision: control.revision + 1 };
      await route.fulfill({ status: 201, json: envelope(rows[0]) }); return;
    }
    if (url.pathname.endsWith("/cancel")) {
      rows = [{ ...rows[0], status: "restoring", restoration_attempts: 1, verification: { status: "uncertain", safe_to_release: false }, reasons: ["restoration_unverified"] }];
      await route.fulfill({ json: envelope(rows[0]) }); return;
    }
    if (url.pathname.endsWith("/return")) {
      expect(body).toEqual({ expected_revision: control.revision, reason: "Reviewed server restoration" });
      rows = [{ ...rows[0], status: "return_blocked", reasons: ["live_return_readiness_failed"] }];
      await route.fulfill({ json: envelope(rows[0]) }); return;
    }
    expect(url.pathname).toBe("/api/v1/autonomy/stop");
    control = { ...control, emergency_stopped: true, revision: control.revision + 1, status: "stopped" };
    await route.fulfill({ json: envelope(control) });
  });
  await page.route(`**/api/v1/intents/${overrideFixture().intent_id}?*`, (route) => route.fulfill({ json: envelope(overrideIntentFixture(session.userId)) }));
  await page.route("**/api/v1/telemetry/paths?*", (route) => route.fulfill({ json: envelope(pathData) }));
  await loginFromUi(page); await expect(page.getByText("edge-1")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.keyboard.press("g"); await page.keyboard.press("n");
  await expect(page.getByTestId("autonomy-mode")).toHaveText("monitor");
  const modelButton = page.getByRole("button", { name: "Model diagnostics", exact: true }); await modelButton.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Frozen model diagnostics" })).toBeVisible();
  await page.getByLabel("Operator history reference").selectOption("measured-history-1");
  await page.getByRole("button", { name: "Run historical inference" }).focus(); await page.keyboard.press("Enter");
  await expect(page.getByText(/Recorded diagnostic 10000000/)).toBeVisible();
  await expect(page.getByText(/Probabilities are action probabilities, not safety confidence/)).toBeVisible();
  await page.getByRole("button", { name: "Versioned configuration", exact: true }).click();
  await page.getByRole("button", { name: "Edit current revision" }).click();
  await page.getByLabel("Requested reward weights (JSON)").fill('{"goodput":2}');
  await page.getByLabel("Configuration change reason").fill("Requested reward revision");
  await page.getByRole("button", { name: "Save new configuration revision" }).click();
  await expect(page.getByText(/Configuration revision recorded/)).toBeVisible();
  await expect(page.getByText("Revision 1: Initial requested settings")).toBeVisible();
  await expect(page.getByText("model_owned_unavailable", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Timed overrides", exact: true }).click();
  await page.getByLabel("Override intent UUID").fill(overrideFixture().intent_id);
  await page.getByLabel("Override execution UUID").fill(overrideFixture().execution_id);
  await page.getByRole("button", { name: "Inspect selected execution" }).click();
  await page.getByLabel("Override reason").fill("Temporary maintenance");
  await expect(page.getByRole("button", { name: "Enroll timed override" })).toBeEnabled();
  await page.getByRole("button", { name: "Enroll timed override" }).click();
  await expect(page.getByText("Override holding", { exact: true })).toBeVisible();
  await expect(page.getByText(/Approximate countdown/)).toBeVisible();
  await page.getByRole("button", { name: "Request restoration" }).click();
  await expect(page.getByText(/Verification status: uncertain/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Request gated return" })).toBeDisabled();
  rows = [{ ...rows[0], status: "restored", restored_at: new Date().toISOString(), verification: { status: "cancelled", safe_to_release: true }, reasons: [] }];
  await page.getByRole("button", { name: "Refresh override status" }).click();
  await page.getByLabel("Explicit return reason").fill("Reviewed server restoration");
  await page.getByRole("button", { name: "Request gated return" }).click();
  await expect(page.getByText("Override return_blocked", { exact: true })).toBeVisible();
  await expect(page.getByText("live_return_readiness_failed", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Emergency stop", exact: true }).focus(); await page.keyboard.press("Enter");
  await expect(page.getByText(/Backend confirmed the emergency latch/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Request gated return" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.goto("/ops/digital-twin");
  await page.getByRole("button", { name: "Show measured probe paths" }).click();
  await page.getByRole("button", { name: "Refresh measured paths" }).click();
  await page.getByLabel("Selected measured probe").selectOption("probe-1");
  await expect(page.getByText(/List fallback: canonical link IDs/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Ordered observed probe hops" })).toContainText("30000000-0000-4000-8000-000000000005");
  pathData = { ...pathsFixture(), status: "partial", paths: pathsFixture().paths.map((path) => ({ ...path, status: "partial" })) };
  await page.getByRole("button", { name: "Refresh measured paths" }).click();
  await expect(page.getByText(/Partial or ambiguous evidence/)).toBeVisible();
  pathData = { ...pathData, status: "stale", freshness: "stale" };
  await page.getByRole("button", { name: "Refresh measured paths" }).click();
  await expect(page.getByText("stale or unavailable", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(writes).toHaveLength(6);
});

import { expect, test } from "@playwright/test";
import { autonomyFixture, certificateFixture, decisionFixture, readyProvidersFixture } from "../../src/features/autonomy/fixtures";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

const envelope = (data: unknown) => ({ success: true, data, meta: { execution_mode: "emulation" }, errors: null });

test("autonomy is non-actuating by default; mobile stop requires a scoped acknowledgement and survives reload", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  let data = autonomyFixture();
  const mutations: unknown[] = [];
  let stops = 0;
  let acknowledge!: () => void;
  const acknowledgement = new Promise<void>((resolve) => { acknowledge = resolve; });
  await page.route("**/api/v1/autonomy**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      expect(new URL(request.url()).searchParams.get("network_id")).toBe(data.network_id);
      await route.fulfill({ json: envelope(data) });
      return;
    }
    expect(request.method()).toBe("POST");
    expect(request.url()).toMatch(/\/autonomy\/stop$/);
    expect(request.headers().authorization).toMatch(/^Bearer /);
    mutations.push(request.postDataJSON());
    stops += 1;
    if (stops === 1) { await route.abort("connectionreset"); return; }
    if (stops === 2) {
      await route.fulfill({ json: envelope(autonomyFixture({ emergency_stopped: true, network_id: "wrong-network" })) });
      return;
    }
    await acknowledgement;
    data = autonomyFixture({ status: "uncertain", emergency_stopped: true, cancellation_status: "uncertain",
      active_execution_id: "owned-execution", stopped_at: "2026-09-09T12:00:00Z", stopped_by_user_id: "operator", revision: 1,
      decisions: [decisionFixture({ status: "uncertain", reasons: ["execution_unresolved"], execution_id: "owned-execution",
        safety: { admissible: true, action_id: "route-1", model_version: "bounded-fluid-v1", reasons: [], evidence: [], certificate: certificateFixture() } })] });
    await route.fulfill({ json: envelope(data) });
  });
  await loginFromUi(page);
  await expect(page.getByText("edge-1")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: /^Autonomy/ }).click();
  await expect(page.getByTestId("autonomy-mode")).toHaveText("monitor");
  await expect(page.getByLabel("Requested mode")).toHaveValue("monitor");
  await expect(page.getByLabel("Checkpoint SHA-256")).toHaveValue("");
  await expect(page.getByRole("option", { name: "Autonomous (unavailable)" })).toHaveJSProperty("disabled", true);
  await expect(page.getByText("Online learning disabled")).toBeVisible();
  await expect(page.getByText(/not a global or continuous-time stability proof/)).toBeVisible();
  expect(mutations).toEqual([]);
  await page.getByRole("button", { name: "Emergency stop", exact: true }).click();
  await expect(page.getByText(/Stop failed: latch unconfirmed/)).toBeVisible();
  await expect(page.getByText(/Backend confirmed the emergency latch/)).toHaveCount(0);
  await page.getByRole("button", { name: "Emergency stop", exact: true }).click();
  await expect(page.getByText(/Stop failed: latch unconfirmed.*does not match the selected scope/)).toBeVisible();
  await page.getByRole("button", { name: "Emergency stop", exact: true }).click();
  await expect(page.getByText(/Stop requested. Latch unconfirmed/)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(/Backend confirmed the emergency latch/)).toHaveCount(0);
  acknowledge();
  await expect(page.getByText(/Backend confirmed the emergency latch. Cancellation: uncertain/)).toBeVisible();
  expect(mutations).toEqual(Array.from({ length: 3 }, () => ({ network_id: data.network_id })));
  await page.reload();
  await expect(page.getByText(/Last reported latch:/)).toContainText("latched. Cancellation: uncertain");
  await expect(page.getByText("execution_unresolved", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Reported conditional certificate" })).toBeVisible();
  await expect(page.getByText(/Expired by browser clock/)).toBeVisible();
  await expect(page.getByText("a".repeat(64), { exact: true })).toBeVisible();
  await page.getByText("Decision evidence and conditional assessment").click();
  await expect(page.locator("details").filter({ has: page.getByText("Decision evidence and conditional assessment", { exact: true }) }).locator(".autonomy-evidence")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(mutations).toHaveLength(3);
});

test("pending PUT cannot clear newer stop; conflict refreshes without retry until explicit new-revision submission", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  let data = autonomyFixture({ revision: 14 });
  const puts: { expected_revision: number; mode: string }[] = [];
  let releaseOldPut!: () => void;
  const oldPut = new Promise<void>((resolve) => { releaseOldPut = resolve; });
  let reads = 0;
  await page.route("**/api/v1/autonomy**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      reads += 1;
      await route.fulfill({ json: envelope(data) });
      return;
    }
    if (request.method() === "POST") {
      expect(request.url()).toMatch(/\/autonomy\/stop$/);
      expect(request.postDataJSON()).toEqual({ network_id: data.network_id });
      data = { ...data, revision: data.revision + 1, emergency_stopped: true, status: "stopped" };
      await route.fulfill({ json: envelope(data) });
      return;
    }
    expect(request.method()).toBe("PUT");
    puts.push(request.postDataJSON());
    if (puts.length === 1) {
      expect(puts[0].expected_revision).toBe(14);
      await oldPut;
      await route.fulfill({ status: 409, json: { success: false, data: null, meta: {}, errors: {
        code: "AUTONOMY_REVISION_CONFLICT", message: "Control revision changed; refresh and explicitly resubmit.",
      } } });
      return;
    }
    expect(puts[1].expected_revision).toBe(15);
    data = { ...data, revision: 16, mode: "recommend", emergency_stopped: false, status: "blocked" };
    await route.fulfill({ json: envelope(data) });
  });
  await loginFromUi(page);
  await expect(page.getByText("edge-1")).toBeVisible();
  await page.getByRole("link", { name: /^Autonomy/ }).click();
  await expect(page.getByRole("button", { name: "Apply configuration" })).toBeEnabled();
  await page.getByLabel("Requested mode").selectOption("recommend");
  await page.getByRole("button", { name: "Apply configuration" }).click();
  await expect.poll(() => puts.length).toBe(1);
  await page.getByRole("button", { name: "Emergency stop", exact: true }).click();
  await expect(page.getByText(/Backend confirmed the emergency latch/)).toBeVisible();
  await expect(page.getByText(/Last reported latch/)).toContainText("latched");
  const readsBeforeConflict = reads;
  releaseOldPut();
  await expect(page.getByText(/Mode change not confirmed.*Control revision changed/)).toBeVisible();
  await expect.poll(() => reads).toBeGreaterThan(readsBeforeConflict);
  await expect(page.getByTestId("autonomy-mode")).toHaveText("monitor");
  await expect(page.getByText(/Last reported latch/)).toContainText("latched");
  await expect(page.getByRole("button", { name: "Apply configuration" })).toBeEnabled();
  expect(puts).toHaveLength(1);
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("button", { name: "Apply configuration" })).toBeEnabled();
  expect(puts).toHaveLength(1);
  await page.getByRole("button", { name: "Apply configuration" }).click();
  await expect(page.getByTestId("autonomy-mode")).toHaveText("recommend");
  await expect(page.getByText(/Last reported latch/)).toContainText("not latched");
  expect(puts).toHaveLength(2);
});

test("autonomous gate denial preserves confirmed recommendation mode and never auto-selects a model", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  const data = autonomyFixture({ mode: "recommend", status: "ready", ready: true, blocked_reasons: [], checkpoint_sha256: "b".repeat(64),
    providers: readyProvidersFixture() });
  const mutations: unknown[] = [];
  await page.route("**/api/v1/autonomy**", async (route) => {
    if (route.request().method() === "GET") { await route.fulfill({ json: envelope(data) }); return; }
    expect(route.request().method()).toBe("PUT");
    mutations.push(route.request().postDataJSON());
    await route.fulfill({ status: 409, json: { success: false, data: null, meta: {},
      errors: { code: "AUTONOMY_NOT_READY", message: "qualified_checkpoint_unavailable, calibrated_safety_unavailable" } } });
  });
  await loginFromUi(page);
  await expect(page.getByText("edge-1")).toBeVisible();
  await page.keyboard.press("g");
  await page.keyboard.press("n");
  await expect(page).toHaveURL(/\/ops\/autonomy$/);
  await expect(page.getByTestId("autonomy-mode")).toHaveText("recommend");
  await expect(page.getByLabel("Checkpoint SHA-256")).toHaveValue("");
  await page.getByLabel("Requested mode").selectOption("autonomous");
  await page.getByLabel("Checkpoint SHA-256").fill("a".repeat(64));
  const expiry = await page.evaluate(() => {
    const date = new Date(Date.now() + 1_800_000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  });
  await page.getByLabel("Approval expiry (local time)").fill(expiry);
  await page.getByRole("button", { name: "Apply configuration" }).click();
  await expect(page.getByText(/Mode change not confirmed.*qualified_checkpoint_unavailable/)).toBeVisible();
  await expect(page.getByTestId("autonomy-mode")).toHaveText("recommend");
  expect(mutations).toEqual([{ network_id: data.network_id, expected_revision: data.revision, mode: "autonomous", checkpoint_sha256: "a".repeat(64), approval_expires_at: expect.stringMatching(/Z$/) }]);
});

test("read-only autonomy permits status and durable polling but no mutations", async ({ page }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ json: envelope({ user_id: state.userId, email: state.email, display_name: "Reader", roles: ["Read-Only"], permissions: ["read:telemetry", "read:topology"] }) });
  });
  let reads = 0;
  let decisionAvailable = false;
  await page.route("**/api/v1/autonomy**", async (route) => {
    expect(route.request().method()).toBe("GET");
    reads += 1;
    await route.fulfill({ json: envelope(autonomyFixture({ decisions: decisionAvailable ? [decisionFixture()] : [] })) });
  });
  await loginFromUi(page);
  await expect(page.getByText("edge-1")).toBeVisible();
  await page.getByRole("link", { name: /^Autonomy/ }).click();
  await expect(page.getByTestId("autonomy-mode")).toHaveText("monitor");
  await expect(page.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Emergency stop", exact: true })).toBeDisabled();
  await expect(page.getByText(/Read-only: changes and stop require/)).toBeVisible();
  await expect(page.locator(".autonomy-decision")).toHaveCount(0);
  decisionAvailable = true;
  await expect(page.locator(".autonomy-decision")).toHaveCount(1, { timeout: 15_000 });
  expect(reads).toBeGreaterThan(1);
});

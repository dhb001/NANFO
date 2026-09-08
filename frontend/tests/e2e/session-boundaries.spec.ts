import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test("logout revokes the session and removes persisted identity and context", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  let logoutCalls = 0;
  await page.route("**/api/v1/auth/logout", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers().authorization).toMatch(/^Bearer /);
    logoutCalls += 1;
    await route.fulfill({ json: { success: true, data: { logged_out: true }, meta: {}, errors: null } });
  });
  await page.goto("/login");
  await expect(page.getByLabel("Email")).toHaveValue("");
  await expect(page.getByLabel("Password")).toHaveValue("");
  await loginFromUi(page);
  await expect(page.getByText("edge-1")).toBeVisible();
  await page.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(logoutCalls).toBe(1);
  const persisted = await page.evaluate(() => [...Object.keys(localStorage), ...Object.keys(sessionStorage)].filter((key) =>
    key.startsWith("nanfo.auth.") || key.startsWith("nanfo.workspace.")));
  expect(persisted).toEqual([]);
  await page.goto("/ops/audit");
  await expect(page).toHaveURL(/\/login$/);
});

test("read-only profile cannot execute actions or enter audit via direct navigation", async ({ page }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  let healthCalls = 0;
  let pluginCalls = 0;
  await page.route("**/api/v1/telemetry/health", async (route) => { healthCalls += 1; await route.abort(); });
  await page.route("**/api/v1/plugins**", async (route) => { pluginCalls += 1; await route.abort(); });
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ json: { success: true, data: {
      user_id: state.userId, email: "reader@example.com", display_name: "Reader",
      roles: ["Read-Only"], permissions: ["read:topology", "read:telemetry"],
    }, meta: { execution_mode: "demo" }, errors: null } });
  });
  await loginFromUi(page);
  await expect(page.getByRole("button", { name: "Create Network" })).toBeDisabled();
  await expect(page.getByRole("link", { name: /^Audit/ })).toHaveCount(0);
  await page.goto("/ops/audit");
  await expect(page.getByText("Permission denied", { exact: true })).toBeVisible();
  await expect(page.getByText(/Demo mode: synthetic data/)).toBeVisible();
  await page.getByRole("link", { name: /^Intent/ }).click();
  await expect(page.getByRole("button", { name: "Validate", exact: true })).toBeDisabled();
  await page.getByRole("link", { name: /^Telemetry/ }).click();
  await expect(page.getByText("Telemetry health restricted", { exact: true })).toBeVisible();
  await expect(page.getByText("Telemetry History", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Plugins/ })).toHaveCount(0);
  await page.goto("/ops/plugins");
  await expect(page.getByText("Permission denied", { exact: true })).toBeVisible();
  expect(healthCalls).toBe(0);
  expect(pluginCalls).toBe(0);
});

test("independent tabs do not inherit or clear each other's sessions", async ({ page, context }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  await loginFromUi(page);
  await expect(page.getByText("edge-1")).toBeVisible();
  const second = await context.newPage();
  await installSessionMocks(second, state);
  await second.goto("/ops/overview");
  await expect(second).toHaveURL(/\/login$/);
  await expect(second.getByLabel("Email")).toHaveValue("");
  await loginFromUi(second);
  await second.route("**/api/v1/auth/logout", async (route) => {
    await route.fulfill({ json: { success: true, data: { logged_out: true }, meta: {}, errors: null } });
  });
  await second.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(second).toHaveURL(/\/login$/);
  await page.reload();
  await expect(page.getByText("edge-1")).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("nanfo.auth.session"))).not.toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("nanfo.auth.session"))).toBeNull();
});

test("a new window with an opener discards copied credentials", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  await loginFromUi(page);
  const popupPromise = page.waitForEvent("popup");
  await page.evaluate(() => { window.open("/ops/overview", "_blank"); });
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/\/login$/);
  await expect(popup.getByLabel("Email")).toHaveValue("");
  expect(await popup.evaluate(() => sessionStorage.getItem("nanfo.auth.session"))).toBeNull();
  expect(await page.evaluate(() => sessionStorage.getItem("nanfo.auth.session"))).not.toBeNull();
});

test("logout with expired access rotates once and revokes the refreshed session", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  const calls: string[] = [];
  await page.route("**/api/v1/auth/logout", async (route) => {
    calls.push("logout");
    if (calls.length === 1) {
      await route.fulfill({ status: 401, json: { success: false, data: null, meta: {}, errors: { code: "UNAUTHORIZED", message: "Access expired" } } });
    } else {
      expect(route.request().headers().authorization).toBe("Bearer rotated-access");
      await route.fulfill({ json: { success: true, data: { logged_out: true }, meta: {}, errors: null } });
    }
  });
  await page.route("**/api/v1/auth/refresh", async (route) => {
    calls.push("refresh");
    await route.fulfill({ json: { success: true, data: { access_token: "rotated-access", refresh_token: "rotated-refresh", token_type: "bearer", expires_in: 900 }, meta: {}, errors: null } });
  });
  await loginFromUi(page);
  await page.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(calls).toEqual(["logout", "refresh", "logout"]);
  expect(await page.evaluate(() => sessionStorage.getItem("nanfo.auth.session"))).toBeNull();
});

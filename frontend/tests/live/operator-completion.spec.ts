import { expect, test } from "@playwright/test";

test("ADR018 backend-live read surfaces preserve server scope and safety boundaries", async ({ page }) => {
  const { E2E_LIVE_FRONTEND_URL: url, E2E_LIVE_EMAIL: email, E2E_LIVE_PASSWORD: password,
    E2E_LIVE_ORGANIZATION_ID: organizationId, E2E_LIVE_WORKSPACE_ID: workspaceId, E2E_LIVE_NETWORK_ID: networkId } = process.env;
  test.skip(!url || !email || !password || !organizationId || !workspaceId || !networkId,
    "Requires an explicitly provisioned live deployment, operator credentials and network scope. No mocked fallback.");
  await page.goto("/login");
  await page.getByLabel("Email").fill(email!); await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL(/\/ops\/overview$/);
  // Set only tab-local selection, never credentials or permissions; every API authorizes it.
  await page.evaluate(({ organizationId, workspaceId, networkId }) => {
    sessionStorage.setItem("nanfo.workspace.organizationId", organizationId);
    sessionStorage.setItem("nanfo.workspace.workspaceId", workspaceId);
    sessionStorage.setItem("nanfo.workspace.networkId", networkId);
  }, { organizationId: organizationId!, workspaceId: workspaceId!, networkId: networkId! });
  const statusResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/autonomy" && response.request().method() === "GET");
  await page.goto("/ops/autonomy");
  const status = await (await statusResponse).json(); expect(status.success).toBe(true);
  expect(status.data.network_id).toBe(networkId); expect(status.data.workspace_id).toBe(workspaceId);
  expect(status.data.online_learning).toBe(false); expect(status.data.production_dispatch).toBe(false);
  await expect(page.getByTestId("autonomy-mode")).toHaveText(status.data.mode);
  for (const [button, path] of [["Model diagnostics", "model"], ["Versioned configuration", "configuration"], ["Timed overrides", "overrides"]]) {
    const response = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/v1/autonomy/${path}` && r.request().method() === "GET");
    await page.getByRole("button", { name: button, exact: true }).click();
    const payload = await (await response).json(); expect(payload.success).toBe(true); expect(payload.data.network_id).toBe(networkId);
    if (path === "model") {
      expect(payload.data.safety_authorized).toBe(false); expect(payload.data.production_dispatch).toBe(false);
      await expect(page.getByRole("heading", { name: "Frozen model diagnostics" })).toBeVisible();
    }
    if (path === "configuration") {
      expect(payload.data.effective_training_status).toBe("model_owned_unavailable"); expect(payload.data.effective_training).toBeNull();
      await expect(page.getByRole("heading", { name: "Immutable configuration history" })).toBeVisible();
    }
  }
  await page.goto("/ops/digital-twin");
  await page.getByRole("button", { name: "Show measured probe paths" }).click();
  const pathsResponse = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v1/telemetry/paths");
  await page.getByRole("button", { name: "Refresh measured paths" }).click();
  const paths = await (await pathsResponse).json(); expect(paths.success).toBe(true); expect(paths.data.network_id).toBe(networkId);
  expect(paths.data.scope).toBe("selected_probe_only");
  await expect(page.getByText(/Observed paths apply only to selected probes/)).toBeVisible();
});

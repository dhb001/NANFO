import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test("audit pages beyond 120, accessible details and narrow/zoomed flow never overlap", async ({ page }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  const requests: URLSearchParams[] = [];
  await page.route("**/api/v1/audit/logs?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    requests.push(query);
    const current = Number(query.get("page")), size = Number(query.get("page_size"));
    await route.fulfill({ json: { success: true, data: { page: current, page_size: size, total: 125,
      items: Array.from({ length: Math.min(size, 125 - (current - 1) * size) }, (_, i) => {
        const n = (current - 1) * size + i + 1;
        return { log_id: `log-${n}`, event_type: `network.changed.${n}.${"long-event-".repeat(15)}`,
          actor_id: "00000000-0000-0000-0000-000000000123", resource_type: "network", resource_id: `resource-${n}`,
          org_id: state.orgId, correlation_id: "00000000-0000-0000-0000-000000000456", timestamp: "2026-09-20T00:00:00Z",
          metadata: { before: { name: "previous network" }, after: { name: "new-network-".repeat(80) } } };
      }) }, meta: {}, errors: null } });
  });
  await loginFromUi(page);
  await page.getByRole("link", { name: "Audit" }).click();
  const records = page.getByRole("list", { name: "Audit records" }).getByRole("listitem");
  await expect(records).toHaveCount(50);
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Page 2 of 3" })).toBeVisible();
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(records).toHaveCount(25);
  await expect(page.getByRole("button", { name: "Next page" })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const detail = records.last().locator("summary");
  await detail.focus();
  await page.keyboard.press("Enter");
  await expect(records.last().getByText("resource-125", { exact: true })).toBeVisible();
  await expect(records.last().getByText("00000000-0000-0000-0000-000000000123", { exact: true })).toBeVisible();
  await expect(records.last().locator("pre")).toContainText("previous network");
  const geometry = await records.evaluateAll((rows) => rows.map((row) => {
    const rect = row.getBoundingClientRect(); return { top: rect.top, bottom: rect.bottom };
  }));
  for (let i = 1; i < geometry.length; i++) expect(geometry[i].top).toBeGreaterThanOrEqual(geometry[i - 1].bottom);
  const overflow = await page.evaluate(() => [...document.querySelectorAll(".audit-timeline, .audit-timeline *")].filter((el) => {
    const rect = el.getBoundingClientRect(); return rect.width && rect.right > innerWidth + 1;
  }).map((el) => `${el.tagName}.${el.className}: ${el.getBoundingClientRect().right}`));
  expect(overflow).toEqual([]);
  await page.getByLabel("Search audit records").fill("network.changed");
  await page.getByLabel("Actor ID", { exact: true }).fill("00000000-0000-0000-0000-000000000123");
  await page.getByLabel("Resource type", { exact: true }).fill("network");
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  await expect(records).toHaveCount(50);
  expect(Object.fromEntries(requests.at(-1)!)).toMatchObject({ search: "network.changed", actor_id: "00000000-0000-0000-0000-000000000123", resource_type: "network", org_id: state.orgId, page: "1" });
});

test("server status and submitted search find an older active behind 200 resolved with selected scope", async ({ page }) => {
  const state = createDefaultSessionState();
  await installSessionMocks(page, state);
  const requests: URLSearchParams[] = [];
  await page.route("**/api/v1/alerts?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    requests.push(query);
    const all = Array.from({ length: 201 }, (_, n) => ({
      alert_id: `alert-${n}`, alert_key: n === 200 ? "old-active-incident" : `resolved-${n}`, source: "telemetry",
      status: n === 200 ? "active" : "resolved", severity: "warning", correlation_id: "correlation-1",
      payload: { org_id: state.orgId, workspace_id: state.workspaceId, network_id: state.networks[0].network_id },
      acknowledged_by_user_id: null, resolved_by_user_id: null, acknowledged_at: null, resolved_at: null,
      created_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z",
    }));
    const items = all.filter((item) => (!query.get("status") || item.status === query.get("status"))
      && (!query.get("search") || item.alert_key.includes(query.get("search")!))).slice(0, Number(query.get("limit")));
    await route.fulfill({ json: { success: true, data: { items, total: items.length, status_counts: {} }, meta: {}, errors: null } });
  });
  await loginFromUi(page);
  await page.getByRole("link", { name: "Reliability" }).click();
  await expect(page.getByText("200 matching alerts loaded", { exact: false })).toBeVisible();
  await expect(page.getByText("old-active-incident", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Active", exact: true }).click();
  await expect(page.getByText("old-active-incident", { exact: true })).toBeVisible();
  await expect(page.getByText("1 matching alerts loaded", { exact: false })).toBeVisible();
  expect(requests.at(-1)?.get("workspace_id")).toBe(state.workspaceId);
  expect(requests.at(-1)?.get("network_id")).toBe(state.networks[0].network_id);
  await expect(page.getByText(`Origin: source telemetry; organization ${state.orgId}; workspace ${state.workspaceId}; network ${state.networks[0].network_id}`)).toBeVisible();
  await page.getByLabel("Filter alerts").fill("old-active");
  expect(requests.at(-1)?.get("search")).toBeNull();
  await page.getByRole("button", { name: "Apply alert filters" }).click();
  await expect.poll(() => requests.at(-1)?.get("search")).toBe("old-active");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

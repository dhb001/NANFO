import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

test("bounded telemetry aggregation preserves ports and pagination on desktop and mobile", async ({ page }) => {
  await installSessionMocks(page, createDefaultSessionState());
  const queries: URLSearchParams[] = [];
  await page.route("**/api/v1/telemetry/history**", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    queries.push(params);
    const aggregation = params.get("aggregation");
    await route.fulfill({ json: {
      success: true, meta: {}, errors: null,
      data: {
        items: aggregation ? [1, 2].map((port) => ({
          device_id: "switch", metric: "queue_backlog_bytes", unit: "bytes", source: "emulation",
          port_no: String(port), peer_host: `h${port}`, run_id: `run-${port}`, bucket_start: "2026-09-08T00:00:00Z", value: port * 100, sample_count: 4,
        })) : [], total: aggregation ? 122 : 0, page: Number(params.get("page")), page_size: 120,
      },
    } });
  });
  await loginFromUi(page);
  await page.getByRole("link", { name: "Telemetry" }).click();
  await expect(page.getByText("No telemetry history")).toBeVisible();
  await page.getByLabel("Aggregation", { exact: true }).selectOption("avg");
  await expect(page.getByRole("alert")).toContainText("Aggregation requires");
  expect(queries.some((params) => params.has("aggregation"))).toBe(false);
  await page.getByLabel("Filter telemetry metric").fill("queue_backlog_bytes");
  await page.getByLabel("Start time", { exact: true }).fill("2026-09-08T00:00");
  await page.getByLabel("End time", { exact: true }).fill("2026-09-08T01:00");
  await expect(page.getByText("100 bytes", { exact: true })).toBeVisible();
  await expect(page.getByText("200 bytes", { exact: true })).toBeVisible();
  await expect(page.getByText(/Port 1/)).toBeVisible();
  await expect(page.getByText(/Port 2/)).toBeVisible();
  await expect(page.getByText(/Peer h1 \| Run run-1/)).toBeVisible();
  await expect(page.getByText(/Peer h2 \| Run run-2/)).toBeVisible();
  expect(queries.at(-1)?.get("start_time")).toMatch(/Z$/);
  expect(queries.at(-1)?.get("bucket_seconds")).toBe("60");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 / 2 | 122 buckets")).toBeVisible();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await page.getByLabel("Bucket seconds").fill("120");
  await expect(page.getByText("Page 1 / 2 | 122 buckets")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Start time", { exact: true })).toBeVisible();
  await expect(page.getByText("200 bytes", { exact: true })).toBeVisible();
  await page.getByLabel("End time", { exact: true }).fill("2026-09-07T01:00");
  await expect(page.getByRole("alert")).toContainText("Start must be before");
  await expect(page.getByText("100 bytes", { exact: true })).not.toBeVisible();
  await page.getByLabel("End time", { exact: true }).fill("2026-09-08T01:00");
  await page.getByLabel("Filter telemetry metric").fill("flow_byte_count");
  await expect(page.getByRole("alert")).toContainText("no durable flow match identity");
  expect(queries.some((params) => params.get("metric") === "flow_byte_count" && params.has("aggregation"))).toBe(false);
  await page.getByLabel("Aggregation", { exact: true }).selectOption("");
  await expect(page.getByText("No telemetry history")).toBeVisible();
  expect(queries.at(-1)?.get("metric")).toBe("flow_byte_count");
  expect(queries.at(-1)?.has("aggregation")).toBe(false);
});

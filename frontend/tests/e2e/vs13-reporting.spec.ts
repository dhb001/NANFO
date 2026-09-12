import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";
import { reportBytes, reportHash } from "./support/report-bytes";

test.describe("ADR019 report browser contracts (mocked bytes, not worker evidence)", () => {
  for (const format of ["pdf", "csv"]) test(`authorized ${format} download has exact fixture bytes and hash`, async ({ page }) => {
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);
    await loginFromUi(page);
    await page.getByRole("link", { name: "Reports" }).click();
    await page.getByLabel("Output Format").selectOption(format);
    await page.getByRole("button", { name: "Generate Report" }).click();
    await expect(page.getByText("status generated", { exact: true })).toBeVisible();
    await expect(page.getByText(/fixture_not_live_measurements/)).toBeVisible();
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: `Download ${format.toUpperCase()}` }).click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe(`fixture-report.${format}`);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    const actual = Buffer.concat(chunks);
    expect(actual).toEqual(reportBytes(format));
    expect(reportHash(actual)).toBe(state.reports[0].artifacts[0].checksum_sha256);
    await expect(page.getByRole("status").filter({ hasText: "actual bytes received" })).toContainText(`${actual.length} actual bytes received; SHA-256 verified`);
    await expect(page.getByText(/s3:\/\//)).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh History" }).click();
    await expect(page.getByRole("button", { name: /executive_summary \/.*generated/ })).toBeVisible();
  });

  test("failed job has no artifacts; reviewed retry can produce a fixture artifact", async ({ page }) => {
    const state = createDefaultSessionState(); state.reportFailure = true;
    await installSessionMocks(page, state);
    await loginFromUi(page);
    await page.getByRole("link", { name: "Reports" }).click();
    await page.getByRole("button", { name: "Generate Report" }).click();
    await expect(page.getByText("Report generation failed", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Download/ })).toHaveCount(0);
    state.reportFailure = false;
    await page.getByRole("button", { name: "Retry Failed Report" }).click();
    await expect(page.getByText(/Review the current form/)).toBeVisible();
    await page.getByRole("button", { name: "Generate Report" }).click();
    await expect(page.getByText("status generated", { exact: true })).toBeVisible();
  });

  test("mobile download rejects tampered bytes and scoped denial", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const state = createDefaultSessionState();
    await installSessionMocks(page, state);
    await loginFromUi(page);
    await page.getByRole("link", { name: "Reports" }).click();
    await page.getByLabel("Output Format").selectOption("csv");
    await page.getByRole("button", { name: "Generate Report" }).click();
    await expect(page.getByRole("button", { name: "Download CSV" })).toBeVisible();
    let denied = false;
    await page.route("**/api/v1/reports/*/download?*", async (route) => {
      expect(route.request().headers().authorization).toBe("Bearer token-1");
      if (denied) await route.fulfill({ status: 403, json: { success: false, data: null, meta: {}, errors: { code: "DENIED", message: "Workspace membership revoked" } } });
      else await route.fulfill({ body: Buffer.alloc(reportBytes("csv").length), contentType: "text/csv" });
    });
    await page.getByRole("button", { name: "Download CSV" }).click();
    await expect(page.getByText("Artifact checksum mismatch. Download blocked.")).toBeVisible();
    denied = true;
    await page.getByRole("button", { name: "Download CSV" }).click();
    await expect(page.getByText("Workspace membership revoked")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});

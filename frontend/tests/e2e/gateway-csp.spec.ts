import { existsSync, readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { createDefaultSessionState, installSessionMocks, loginFromUi } from "./support/session";

// The gateway keeps its security headers in an include shared by every location
// (deploy/nginx-security-headers.conf); older layouts inline them in nginx.conf.
const gatewayFiles = ["../../../deploy/nginx-security-headers.conf", "../../../deploy/nginx.conf"]
  .map((file) => new URL(file, import.meta.url)).filter((file) => existsSync(file));
const policy = gatewayFiles.map((file) => readFileSync(file, "utf8").match(/add_header Content-Security-Policy "([^"]+)" always;/)?.[1])
  .find((value) => value !== undefined);
if (!policy) throw new Error("Gateway CSP missing");

test("gateway CSP serves fonts, scripts and connections from the same origin only (ADR-028 item 12)", () => {
  const directives = Object.fromEntries(policy.split(";").map((part) => part.trim().split(/\s+/)).filter((part) => part[0]).map(([name, ...values]) => [name, values]));
  expect(directives["font-src"]).toEqual(["'self'"]);
  expect(directives["script-src"]).toEqual(["'self'"]);
  expect(directives["connect-src"]).toContain("'self'");
  expect(policy).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
});

test("gateway CSP permits React login, Twin, inline styles and blob resources", async ({ page }) => {
  await page.route("**/*", async (route) => {
    if (route.request().resourceType() !== "document") return route.fallback();
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), "content-security-policy": policy } });
  });
  await page.addInitScript(() => {
    Object.assign(window, { cspViolations: [] as string[] });
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as unknown as { cspViolations: string[] }).cspViolations.push(event.violatedDirective);
    });
  });
  await installSessionMocks(page, createDefaultSessionState());
  await loginFromUi(page);
  await page.locator(".network-choice").filter({ hasText: "Network A" }).click();
  await page.getByRole("link", { name: "Digital Twin", exact: true }).click();
  await expect(page.getByText("3D Digital Twin")).toBeVisible();
  await page.getByLabel("Campus model file").setInputFiles({
    name: "campus.gltf",
    mimeType: "model/gltf+json",
    buffer: Buffer.from(JSON.stringify({ asset: { version: "2.0" }, scenes: [{ nodes: [0] }], nodes: [{ name: "campus" }], scene: 0 })),
  });
  await expect(page.getByText(/model GLTF/i)).toBeVisible();
  const result = await page.evaluate(async () => {
    const element = document.createElement("div");
    element.style.color = "rgb(1, 2, 3)";
    document.body.append(element);
    const color = getComputedStyle(element).color;
    element.remove();
    const data = URL.createObjectURL(new Blob(["asset"]));
    const workerUrl = URL.createObjectURL(new Blob(["postMessage('worker-ok')"], { type: "text/javascript" }));
    const worker = new Worker(workerUrl);
    try {
      const workerResult = await new Promise<string>((resolve, reject) => {
        worker.onmessage = (event) => resolve(event.data as string);
        worker.onerror = reject;
      });
      return { color, body: await (await fetch(data)).text(), workerResult };
    } finally {
      worker.terminate();
      URL.revokeObjectURL(data);
      URL.revokeObjectURL(workerUrl);
    }
  });
  expect(result).toEqual({ color: "rgb(1, 2, 3)", body: "asset", workerResult: "worker-ok" });
  expect(await page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations)).toEqual([]);
});

test("gateway CSP prevents same-origin framing", async ({ page }) => {
  await page.route("**/csp-parent", (route) => route.fulfill({
    contentType: "text/html", body: '<iframe src="/csp-child"></iframe>',
  }));
  await page.route("**/csp-child", (route) => route.fulfill({
    contentType: "text/html", headers: { "content-security-policy": policy },
    body: "<script>parent.postMessage('framed-secret', '*')</script>",
  }));
  await page.addInitScript(() => {
    Object.assign(window, { framedSecret: false });
    window.addEventListener("message", (event) => {
      if (event.data === "framed-secret") Object.assign(window, { framedSecret: true });
    });
  });
  const refused = page.waitForEvent("console", { predicate: (message) => message.text().includes("frame-ancestors") });
  await page.goto("/csp-parent");
  await refused;
  expect(await page.evaluate(() => (window as unknown as { framedSecret: boolean }).framedSecret)).toBe(false);
});

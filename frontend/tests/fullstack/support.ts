import { readFileSync, statSync } from "node:fs";
import { expect, type Page, type APIRequestContext, type Response } from "@playwright/test";

export function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`R09 missing ${name}; use backend/scripts/review_fullstack.py`);
  return value;
}

export function loopback(name: string): string {
  const value = required(name);
  const url = new URL(value);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port || url.pathname !== "/" || url.username || url.password || url.search || url.hash) {
    throw new Error(`R09 requires a bare owned loopback origin for ${name}`);
  }
  return url.origin;
}

interface Identity { email: string; password: string; user_id: string }
interface Tenant { org_id: string; workspace_id: string; network_id: string }
interface Fixture { users: Record<"owner" | "member" | "outsider", Identity>; owner: Tenant; outsider: Tenant }
const fixturePath = required("R09_FIXTURE");
const info = statSync(fixturePath);
if ((info.mode & 0o077) !== 0 || info.uid !== process.getuid?.()) throw new Error("R09 fixture must be UID-private");
export const fixture: Fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
export const apiOrigin = loopback("R09_API_URL");

export async function login(page: Page, identity: keyof Fixture["users"] = "owner") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(fixture.users[identity].email);
  await page.getByLabel("Password").fill(fixture.users[identity].password);
  await expect(page.getByRole("button", { name: /^Sign In(?:\s*↗)?$/ })).toBeVisible();
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url() === `${apiOrigin}/api/v1/auth/login` && r.request().method() === "POST", { timeout: 20_000 }),
    page.getByRole("button", { name: /^Sign In(?:\s*↗)?$/ }).click(),
  ]);
  expect(response.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();
}

export async function selectNetwork(page: Page) {
  await page.getByRole("combobox", { name: "Organization", exact: true }).selectOption(fixture.owner.org_id);
  await page.getByRole("combobox", { name: "Workspace", exact: true }).selectOption(fixture.owner.workspace_id);
  await page.locator("button.network-choice").filter({ hasText: "R09 network 01" }).click();
}

export async function session(page: Page): Promise<{ accessToken: string; refreshToken: string }> {
  return page.evaluate(() => {
    const value = sessionStorage.getItem("nanfo.auth.session");
    if (!value) throw new Error("Real UI login session missing");
    return JSON.parse(value);
  });
}

export async function api(request: APIRequestContext, token: string, method: string, path: string, data?: unknown, status = 200) {
  const response = await request.fetch(`${apiOrigin}${path}`, {
    method, headers: { Authorization: `Bearer ${token}` }, ...(data === undefined ? {} : { data }),
  });
  expect(response.status(), `${method} ${path}`).toBe(status);
  if (status === 204) return null;
  const body = await response.json();
  expect(Object.keys(body).sort()).toEqual(["data", "errors", "meta", "success"]);
  expect(body.success).toBe(status < 400);
  return body.data;
}

export function pathResponse(page: Page, path: string, method = "GET"): Promise<Response> {
  return page.waitForResponse((r) => new URL(r.url()).pathname === path && r.request().method() === method);
}

export function triangle() {
  const positions = Buffer.from(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]).buffer);
  return Buffer.from(JSON.stringify({
    asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
    buffers: [{ uri: `data:application/octet-stream;base64,${positions.toString("base64")}`, byteLength: positions.length }],
    bufferViews: [{ buffer: 0, byteLength: positions.length }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: "VEC3", min: [0, 0, 0], max: [1, 1, 0] }],
  }));
}

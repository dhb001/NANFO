import { describe, expect, it } from "vitest";
import { assertProductionBaseUrls, baseUrlProblems, isLoopbackHostname } from "./apiBaseGuard";

const build = (env: Record<string, string | undefined>, extra: { mode?: string; allowLoopback?: boolean } = {}) =>
  baseUrlProblems({ command: "build", mode: extra.mode ?? "production", env, allowLoopback: extra.allowLoopback });

describe("production base URL guard (ADR-028 C16)", () => {
  it("recognizes loopback hosts in every spelling", () => {
    for (const host of ["localhost", "LOCALHOST", "api.localhost", "127.0.0.1", "127.8.9.10", "0.0.0.0", "[::1]", "::1",
      "[::ffff:7f00:1]", "0:0:0:0:0:0:0:1", "localhost."]) {
      expect(isLoopbackHostname(host), host).toBe(true);
    }
    for (const host of ["gateway.example", "10.0.0.1", "128.0.0.1", "[2001:db8::1]", "mylocalhost.example"]) {
      expect(isLoopbackHostname(host), host).toBe(false);
    }
  });

  it("allows same-origin production builds (unset, blank or path prefix)", () => {
    expect(build({})).toEqual([]);
    expect(build({ VITE_API_BASE_URL: "", VITE_WS_BASE_URL: " " })).toEqual([]);
    expect(build({ VITE_API_BASE_URL: "/nanfo", VITE_WS_BASE_URL: "/nanfo" })).toEqual([]);
    expect(build({ VITE_API_BASE_URL: "https://api.example", VITE_WS_BASE_URL: "wss://api.example" })).toEqual([]);
  });

  it("fails production builds whose API or WebSocket base points at loopback", () => {
    expect(build({ VITE_API_BASE_URL: "http://127.0.0.1:8000" })).toEqual([
      expect.stringContaining("VITE_API_BASE_URL points at loopback"),
    ]);
    expect(build({ VITE_WS_BASE_URL: "ws://localhost:8000/" })).toEqual([
      expect.stringContaining("VITE_WS_BASE_URL points at loopback"),
    ]);
    expect(() => assertProductionBaseUrls({ command: "build", mode: "production", env: { VITE_API_BASE_URL: "http://[::1]:8000" } }))
      .toThrow(/Refusing a production build.*\n.*loopback/);
    // Any non-development build mode is deployable and therefore guarded.
    expect(build({ VITE_API_BASE_URL: "http://localhost" }, { mode: "staging" })).toHaveLength(1);
  });

  it("rejects malformed or credential-bearing overrides", () => {
    expect(build({ VITE_API_BASE_URL: "api.example" })[0]).toMatch(/not an absolute URL/);
    expect(build({ VITE_API_BASE_URL: "ftp://api.example" })[0]).toMatch(/unsupported scheme/);
    expect(build({ VITE_API_BASE_URL: "https://user:pw@api.example" })[0]).toMatch(/credentials/);
    expect(build({ VITE_WS_BASE_URL: "wss://api.example/?token=x" })[0]).toMatch(/query string/);
  });

  it("never blocks the dev server, explicit development builds or opted-in local runners", () => {
    const env = { VITE_API_BASE_URL: "http://127.0.0.1:8000", VITE_WS_BASE_URL: "ws://127.0.0.1:8000" };
    expect(baseUrlProblems({ command: "serve", mode: "development", env })).toEqual([]);
    expect(build(env, { mode: "development" })).toEqual([]);
    expect(build(env, { allowLoopback: true })).toEqual([]);
  });
});

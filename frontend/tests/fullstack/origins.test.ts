import { describe, expect, it } from "vitest";
import { loopbackOrigin, resolveOrigins } from "./origins";

describe("R09 full-stack origins (ADR-028 C22)", () => {
  it("defaults API and WebSocket to the gateway page origin", () => {
    expect(resolveOrigins({ R09_BASE_URL: "http://127.0.0.1:8443/" })).toEqual({
      base: "http://127.0.0.1:8443", api: "http://127.0.0.1:8443", ws: "ws://127.0.0.1:8443", sameOrigin: true,
    });
  });

  it("keeps the cross-origin lane via R09_API_URL", () => {
    expect(resolveOrigins({ R09_BASE_URL: "http://127.0.0.1:4173", R09_API_URL: "http://127.0.0.1:8000" })).toEqual({
      base: "http://127.0.0.1:4173", api: "http://127.0.0.1:8000", ws: "ws://127.0.0.1:8000", sameOrigin: false,
    });
  });

  it("refuses non-loopback, path-bearing or credentialed origins", () => {
    for (const value of ["http://example.com:80/", "http://127.0.0.1/", "http://127.0.0.1:1/api", "http://u:p@127.0.0.1:1/", "https://127.0.0.1:1/"]) {
      expect(() => loopbackOrigin("R09_BASE_URL", value)).toThrow();
    }
    expect(() => resolveOrigins({})).toThrow("R09 missing R09_BASE_URL");
  });
});

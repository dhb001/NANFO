import { describe, expect, it } from "vitest";
import { API_BASE_URL, apiUrl, normalizeBaseUrl, resolveWebSocketBase, webSocketBaseUrl } from "@/shared/lib/env";

const https = { protocol: "https:", host: "gateway.example:8443" };
const http = { protocol: "http:", host: "10.0.0.5" };

describe("ADR-028 C16 base URLs", () => {
  it("defaults to same-origin API calls when no override is configured", () => {
    expect(API_BASE_URL).toBe("");
    expect(apiUrl("/api/v1/auth/login")).toBe("/api/v1/auth/login");
  });

  it("normalizes blanks and trailing slashes", () => {
    expect(normalizeBaseUrl(undefined)).toBe("");
    expect(normalizeBaseUrl("   ")).toBe("");
    expect(normalizeBaseUrl(" https://api.example/ ")).toBe("https://api.example");
    expect(normalizeBaseUrl("https://api.example/prefix///")).toBe("https://api.example/prefix");
  });

  it("derives wss: from an https page origin and ws: from http", () => {
    expect(resolveWebSocketBase(undefined, "", https)).toBe("wss://gateway.example:8443");
    expect(resolveWebSocketBase("", "", http)).toBe("ws://10.0.0.5");
    expect(resolveWebSocketBase(undefined, "/nanfo/", https)).toBe("wss://gateway.example:8443/nanfo");
  });

  it("derives the socket origin from an explicit API origin, keeping TLS", () => {
    expect(resolveWebSocketBase(undefined, "https://api.example/", http)).toBe("wss://api.example");
    expect(resolveWebSocketBase(undefined, "http://api.example:8000/base", https)).toBe("ws://api.example:8000/base");
  });

  it("prefers an explicit WebSocket override, normalized", () => {
    expect(resolveWebSocketBase("wss://realtime.example/", "https://api.example", http)).toBe("wss://realtime.example");
    expect(resolveWebSocketBase("https://realtime.example", "", http)).toBe("wss://realtime.example");
    expect(resolveWebSocketBase("/rt/", "", https)).toBe("wss://gateway.example:8443/rt");
  });

  it("uses the current window location at call time", () => {
    expect(webSocketBaseUrl()).toBe(`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`);
    expect(webSocketBaseUrl(https)).toBe("wss://gateway.example:8443");
  });
});

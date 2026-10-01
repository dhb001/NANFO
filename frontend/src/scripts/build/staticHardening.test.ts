// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import config from "../../../vite.config";

const html = readFileSync(new URL("../../../index.html", import.meta.url), "utf8");
const css = ["../../styles/tokens.css", "../../styles/base.css", "../../styles/reset.css"]
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8")).join("\n");

describe("static page hardening (ADR-028 item 12)", () => {
  it("loads no third-party fonts or origins, so the gateway CSP can stay font-src 'self'", () => {
    expect(html).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
    expect(html).not.toMatch(/<link[^>]+(https?:)?\/\//i);
    expect(html).not.toMatch(/<script[^>]+src="(https?:)?\/\//i);
    expect(css).not.toMatch(/@import\s+url\(\s*["']?(https?:)?\/\//i);
    expect(css).not.toMatch(/url\(\s*["']?(https?:)?\/\//i);
    expect(css).toMatch(/--font-ui:\s*"Segoe UI"/);
  });

  it("contains no inline script or event-handler attributes", () => {
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
    expect(scripts.length).toBeGreaterThan(0);
    for (const [, attributes, body] of scripts) {
      expect(attributes).toMatch(/\bsrc="\/src\/main\.tsx"/);
      expect(body.trim()).toBe("");
    }
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  it("emits hidden source maps for production builds (never referenced from bundles)", () => {
    const resolve = config as unknown as (env: { command: "build"; mode: string }) => { build?: { sourcemap?: unknown } };
    const previous = { ...process.env };
    try {
      expect(resolve({ command: "build", mode: "production" }).build?.sourcemap).toBe("hidden");
      expect(resolve({ command: "build", mode: "development" }).build?.sourcemap).toBe(true);
    } finally {
      process.env = previous;
    }
  });
});

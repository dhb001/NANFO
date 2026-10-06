import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173";
// The gateway CSP (script-src 'self') applies to the production bundle; the dev server's
// inline React-refresh preamble would be blocked by it, so CSP tests use a built preview.
const gatewayURL = process.env.E2E_GATEWAY_BASE_URL ?? "http://127.0.0.1:4174";
const previewDir = "node_modules/.cache/nanfo-e2e-dist";

// Same-origin defaults (ADR-028 C16). Empty values override any developer .env;
// mocked routes answer /api and /ws, so the dev proxy stays disabled.
const sameOriginEnv = {
  VITE_API_BASE_URL: "",
  VITE_WS_BASE_URL: "",
  NANFO_DEV_API_PROXY_TARGET: "",
};

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: 1,
  reporter: "list",
  webServer: [
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173",
      url: baseURL,
      reuseExistingServer: true,
      timeout: 120_000,
      env: sameOriginEnv,
    },
    {
      command: `npx vite build --mode production --outDir ${previewDir} --emptyOutDir && npx vite preview --host 127.0.0.1 --port 4174 --strictPort --outDir ${previewDir}`,
      url: gatewayURL,
      reuseExistingServer: true,
      timeout: 240_000,
      env: sameOriginEnv,
    },
  ],
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: /gateway-csp\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "gateway-production",
      testMatch: /gateway-csp\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: gatewayURL },
    },
  ],
});

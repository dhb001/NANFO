import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: 1,
  reporter: "list",
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
    // Same-origin defaults (ADR-028 C16). Empty values override any developer .env;
    // mocked routes answer /api and /ws, so the dev proxy stays disabled.
    env: {
      VITE_API_BASE_URL: "",
      VITE_WS_BASE_URL: "",
      NANFO_DEV_API_PROXY_TARGET: "",
    },
  },
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});

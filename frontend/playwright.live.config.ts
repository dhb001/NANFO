import { defineConfig, devices } from "@playwright/test";

// Separately provisioned frontend/backend deployment. Never starts or resets a lab.
export default defineConfig({
  testDir: "./tests/live", retries: 0, workers: 1, reporter: "list",
  use: { baseURL: process.env.E2E_LIVE_FRONTEND_URL, trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: "chromium-live", use: { ...devices["Desktop Chrome"] } }],
});

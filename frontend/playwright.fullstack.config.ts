import { defineConfig, devices } from "@playwright/test";
import { fixture, required, loopback } from "./tests/fullstack/support";

// Dedicated lane: missing prerequisites fail collection, never silently skip or reuse a dev server.
if (required("R09_PRODUCTION_BUILD") !== "1" || !fixture.users.owner.user_id) {
  throw new Error("R09 requires the owned production-build runner");
}

export default defineConfig({
  testDir: "./tests/fullstack",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  outputDir: required("R09_OUTPUT"),
  reporter: [["junit", { outputFile: required("R09_JUNIT") }]],
  use: {
    baseURL: loopback("R09_BASE_URL"),
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    ...devices["Desktop Chrome"],
    serviceWorkers: "block",
    // Network traces contain passwords/tokens. Runner publishes only counts and build/source hashes.
    trace: "off",
    screenshot: "off",
    video: "off",
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
  },
  projects: [{ name: "production-chromium" }],
});

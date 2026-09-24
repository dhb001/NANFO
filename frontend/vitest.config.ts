import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    // Unit tests run against the production same-origin defaults, whatever a local .env says.
    env: { VITE_API_BASE_URL: "", VITE_WS_BASE_URL: "" },
    exclude: ["tests/e2e/**", "tests/live/**", "tests/fullstack/**", "node_modules/**", "dist/**"],
  },
});

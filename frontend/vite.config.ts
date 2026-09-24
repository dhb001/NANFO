import { defineConfig, loadEnv, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { ALLOW_LOOPBACK_ENV, assertProductionBaseUrls } from "./src/scripts/build/apiBaseGuard";

// Dev server only: same-origin /api and /ws are proxied to a local backend. Set
// NANFO_DEV_API_PROXY_TARGET="" to disable (the mocked Playwright lane does).
function devProxy(): Record<string, ProxyOptions> | undefined {
  const target = process.env.NANFO_DEV_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
  if (!target) return undefined;
  return { "/api": { target }, "/ws": { target, ws: true } };
}

export default defineConfig(({ command, mode }) => {
  assertProductionBaseUrls({
    command,
    mode,
    env: loadEnv(mode, process.cwd(), "VITE_"),
    allowLoopback: process.env[ALLOW_LOOPBACK_ENV] === "1",
  });
  return {
    plugins: [
      react(),
      {
        name: "twin-three-catalogue",
        apply: "build",
        enforce: "pre",
        // Canvas only uses this namespace to register JSX constructors. Keep its
        // lifecycle/events intact while letting Rollup shake unused Three exports.
        resolveId(source, importer) {
          if (source === "three" && importer?.endsWith("/@react-three/fiber/dist/react-three-fiber.esm.js")) {
            return fileURLToPath(new URL("./src/features/digitalTwin/threeCatalogue.ts", import.meta.url));
          }
        },
      },
    ],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: { proxy: devProxy() },
    build: {
      // Maps are emitted for symbolication but never referenced from served bundles.
      sourcemap: mode === "development" ? true : "hidden",
      target: "es2022",
      minify: "terser",
      terserOptions: {
        compress: { passes: 2 },
      },
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom", "react-router-dom"],
            three: ["three", "@react-three/fiber", "three/examples/jsm/loaders/GLTFLoader.js"],
            query: ["@tanstack/react-query"],
          },
        },
      },
    },
  };
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
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
  build: {
    sourcemap: true,
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
});

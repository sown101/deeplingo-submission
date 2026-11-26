import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    // Public source maps are disabled: no private observability pipeline
    // exists to upload them to, and shipped maps expose application source.
    sourcemap: false,
    // No manualChunks: measured (WEB-8C). Rollup's natural splitting puts all
    // framework modules in the entry graph and feature screens in async
    // chunks with minimal duplication; a "framework" vendor chunk moved
    // deduplicated async-only modules INTO the initial graph (+7 KiB) for no
    // total benefit.
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
});

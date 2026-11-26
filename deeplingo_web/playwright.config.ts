import { defineConfig } from "@playwright/test";

// Deterministic browser CI only. These specs run against a locally served
// dev build with ALL backend traffic intercepted by page.route fixtures and
// all external networks (Supabase, YouTube) aborted. They never touch a real
// backend, real auth, or an AI provider. The full Product E2E (scripts/
// e2e_product_v1.mjs) is a separate
// external-integration proof and must not be merged into this gate.
export default defineConfig({
  testDir: "./e2e/deterministic",
  timeout: 30_000,
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    headless: true,
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    // The specs assert English text; the app would otherwise follow the mocked support language (vi).
    storageState: {
      cookies: [],
      origins: [{ origin: "http://localhost:5173", localStorage: [{ name: "deeplingo.ui_language", value: "en" }] }],
    },
  },
  webServer: {
    command: "npm run dev",
    port: 5173,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      // Browser-safe dummy values only; specs block all external network.
      VITE_API_BASE_URL: "/api/v1/v3",
      VITE_SUPABASE_URL: "https://ci-dummy.supabase.co",
      VITE_SUPABASE_PUBLISHABLE_KEY: "ci-dummy-publishable-key",
    },
  },
});

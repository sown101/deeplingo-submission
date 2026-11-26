import { defineConfig } from "@playwright/test";

// Responsive screenshot suite: every screen at ten viewport sizes in Chromium, WebKit (close to Safari) and
// Firefox. Not part of the deterministic CI gate (playwright.config.ts). Run `npm run test:e2e:responsive`, then
// `npm run report:responsive`. Set RESPONSIVE_LANG=vi to run with the Vietnamese interface (longer strings).
const language = process.env.RESPONSIVE_LANG ?? "en";

export default defineConfig({
  testDir: "./e2e/responsive",
  timeout: 45_000,
  fullyParallel: true,
  workers: 4,
  retries: 0,
  reporter: [["list"]],
  use: {
    headless: true,
    storageState: {
      cookies: [],
      origins: [{ origin: "http://localhost:5173", localStorage: [{ name: "deeplingo.ui_language", value: language }] }],
    },
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "webkit", use: { browserName: "webkit" } },
    { name: "firefox", use: { browserName: "firefox" } },
  ],
  webServer: {
    command: "npm run dev",
    port: 5173,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      // Browser-safe dummy values only; the suite blocks all external network.
      VITE_API_BASE_URL: "/api/v1/v3",
      VITE_SUPABASE_URL: "https://ci-dummy.supabase.co",
      VITE_SUPABASE_PUBLISHABLE_KEY: "ci-dummy-publishable-key",
    },
  },
});

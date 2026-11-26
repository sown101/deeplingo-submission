import { expect, test, type Page } from "@playwright/test";

// W05 password-recovery routes — deterministic browser gate.
//
// Proves the recovery entry routes exist on the real router (WEB-9D found
// them missing from the committed tree) and that /reset-password stays
// locked behind an observed PASSWORD_RECOVERY event: neither a signed-out
// visitor nor a normally signed-in learner can reach the reset form. All
// traffic outside the local dev server is aborted — no backend, no Supabase.

async function blockExternal(page: Page): Promise<void> {
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === "http://localhost:5173") return route.continue();
    return route.abort();
  });
}

// Seeds the same Supabase v2 session shape as app.spec.ts.
async function seedSession(page: Page): Promise<void> {
  const session = {
    access_token: "e2e-dummy-jwt.header.token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "dummy-refresh-token",
    user: {
      id: "e2e-user-0001",
      aud: "authenticated",
      role: "authenticated",
      email: "e2e@ci.invalid",
      app_metadata: {},
      user_metadata: {},
      created_at: "2026-01-01T00:00:00Z",
    },
  };
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key, value as string);
    },
    ["sb-ci-dummy-auth-token", JSON.stringify(session)],
  );
}

test.describe("deterministic browser gate — W05 password recovery", () => {
  test("sign-in links to /forgot-password and the route renders the request form", async ({ page }) => {
    await blockExternal(page);
    await page.goto("/signin");
    await page.getByRole("link", { name: "Forgot password?" }).click();
    await expect(page).toHaveURL(/\/forgot-password$/);
    await expect(page.getByRole("heading", { name: "Reset password" })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send reset link" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to Sign in" })).toHaveAttribute("href", "/signin");
  });

  test("/reset-password without a recovery event shows Invalid link for a signed-out visitor", async ({ page }) => {
    await blockExternal(page);
    await page.goto("/reset-password");
    await expect(page.getByRole("heading", { name: "Invalid link" })).toBeVisible();
    await expect(page.getByText("This password-reset link is invalid or has expired.")).toBeVisible();
    await expect(page.getByLabel("New password")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Request new link" })).toHaveAttribute("href", "/forgot-password");
  });

  test("a signed-in learner WITHOUT a recovery event cannot open the reset form", async ({ page }) => {
    await seedSession(page);
    await blockExternal(page);
    await page.goto("/reset-password");
    await expect(page.getByRole("heading", { name: "Invalid link" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Set new password" })).toHaveCount(0);
    await expect(page.getByLabel("New password")).toHaveCount(0);
  });
});

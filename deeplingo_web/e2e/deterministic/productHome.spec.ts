import { expect, test } from "@playwright/test";
import { progressBody } from "./progressFixture";
import { verifyProductHome } from "../../scripts/m1_runtime_helpers.mjs";

const API = "/api/v1/v3/learner/me";
const TOKEN = "home-proof-dummy.header.token";
const item = (index: number, kind: string, status = "open") => ({
  id: `aaaaaaaa-0000-4000-8000-${String(index).padStart(12, "0")}`, kind, status,
  minutes: 3, reason: "Fixture projection", item_count: kind === "review" ? 3 : null,
  library_item_id: kind === "video_practice" ? "11111111-1111-4111-8111-111111111111" : null,
  video_title: kind === "video_practice" ? "Fixture video" : null, companion_entry: null,
});

for (const state of ["populated", "empty", "without-video"] as const) {
  test(`live Home proof accepts current ${state} server projections`, async ({ page }) => {
    await fixture(page, state);
    await verifyProductHome(page, "http://localhost:5173");
    await expect(page.getByRole("group", { name: "Activity", exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: "Cards", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Continue learning", exact: true })).toHaveCount(0);
  });
}

for (const projection of ["plan", "progress"] as const) {
  test(`live Home proof fails closed when the ${projection} projection is unavailable`, async ({ page }) => {
    await fixture(page, "populated", projection);
    await expect(verifyProductHome(page, "http://localhost:5173")).rejects.toThrow("Home projection unavailable");
  });
}

async function fixture(page: import("@playwright/test").Page, state: string, failing?: string) {
  page.setDefaultTimeout(3_000);
  await page.addInitScript(() => {
    localStorage.setItem("deeplingo.ui_language", "en");
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "home-proof-dummy.header.token",
      token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "home-fixture", aud: "authenticated", role: "authenticated", email: "home@ci.invalid",
        app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith("/api/")) {
      return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
    }
    expect(route.request().method()).toBe("GET");
    expect(route.request().headers().authorization).toBe(`Bearer ${TOKEN}`);
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", is_complete: true });
    if (url.pathname === `${API}/${failing}`) return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    // Home also lists the learner's videos (the Library was folded into Home).
    if (url.pathname === `${API}/library/videos`) return json([]);
    if (url.pathname === `${API}/plan`) return json({ plan_id: "home-fixture", day: "2026-11-02", language_code: "en", intro: "Fixture", items:
      state === "empty" ? [] : state === "without-video" ? [item(1, "review")] : [item(1, "video_practice"), item(2, "review"), item(3, "review", "dismissed")] });
    if (url.pathname === `${API}/progress`) {
      const now = new Date();
      const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      return json(progressBody({ heatmap: state === "empty" ? [] : [{ date, count: 7 }],
        cards: state === "empty" ? [] : [{ language_code: "en", total: 5, due: 4, new: 1, learning: 1, review: 2, relearning: 1 }] }));
    }
    throw new Error("Unexpected API path in Home proof fixture");
  });
}

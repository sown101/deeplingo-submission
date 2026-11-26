import { expect, test } from "@playwright/test";
import { progressBody, recentHeat } from "./progressFixture";

const API = "/api/v1/v3/learner/me";
const VIDEO = "11111111-1111-4111-8111-111111111111";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("deeplingo.ui_language", "vi");
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "e2e-dummy-jwt.header.token", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: "dummy-refresh-token",
      user: { id: "e2e-user-0001", aud: "authenticated", role: "authenticated", email: "e2e@ci.invalid",
        app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    }));
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", is_complete: true });
    if (url.pathname === `${API}/plan`) return json({ plan_id: "design-plan", day: "2026-10-31", language_code: "en", intro: "Chào bạn! Hôm nay mình có vài gợi ý nhỏ.", items: [
      { id: "aaaaaaaa-0000-4000-8000-000000000001", kind: "review", status: "open", minutes: 4, reason: "7 mục đã đến lúc ôn.", item_count: 7, library_item_id: null, video_title: null, companion_entry: null },
      { id: "aaaaaaaa-0000-4000-8000-000000000002", kind: "video_practice", status: "open", minutes: 6, reason: "Tiếp tục từ chỗ bạn đã dừng.", item_count: null, library_item_id: VIDEO, video_title: "Du lịch Đà Nẵng", companion_entry: null },
      { id: "aaaaaaaa-0000-4000-8000-000000000003", kind: "conversation", status: "open", minutes: 5, reason: "Chọn một chủ đề rồi nói chuyện với mình.", item_count: null, library_item_id: null, video_title: null, companion_entry: "home" },
    ] });
    if (url.pathname === `${API}/progress`) return json(progressBody({ heatmap: recentHeat(35),
      cards: [{ language_code: "en", total: 5, due: 3, new: 1, learning: 1, review: 2, relearning: 1 }] }));
    if (url.pathname.startsWith("/api/")) return json({});
    if (url.origin === "http://localhost:5173") return route.continue();
    return route.abort();
  });
});

for (const width of [390, 1180, 1440]) {
  for (const colorScheme of ["light", "dark"] as const) {
    test(`Home design ${width}px ${colorScheme}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.goto("/home");
      await expect(page.getByRole("heading", { name: "Trang chủ", level: 1 })).toBeVisible();
      await expect(page.getByRole("group", { name: "Thẻ ôn" })).toBeVisible();
      await expect(page.getByText("3 thẻ đến hạn")).toBeVisible();
      await expect(page.getByRole("link", { name: "Mở trang Tiến bộ" })).toBeVisible();
      await expect(page.getByText("Du lịch Đà Nẵng", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const navigation = await page.getByRole("navigation", { name: "Chính" }).boundingBox();
      expect(navigation).not.toBeNull();
      if (width === 390) {
        expect(navigation!.y).toBeGreaterThan(780);
        expect(navigation!.y + navigation!.height).toBeLessThanOrEqual(900);
        const profile = await page.getByRole("button", { name: "Tài khoản" }).boundingBox();
        expect(profile!.x).toBeGreaterThan(300);
      }
      expect(await page.locator(".home-design").evaluate(el => getComputedStyle(el).backgroundColor)).toBe(colorScheme === "dark" ? "rgb(0, 0, 0)" : "rgb(242, 242, 247)");
      await page.screenshot({ path: info.outputPath(`home-${width}-${colorScheme}.png`), fullPage: true });
      await page.getByRole("link", { name: "Ôn ngay" }).click();
      // "Ôn ngay" lands on the learner's language deck (/review/quick redirects there).
      await expect(page).toHaveURL(/\/review\/en$/);
      await expect(page.locator(".home-design")).toHaveCount(0);
    });
  }
}

test("Home plan failure retries without showing a completed state", async ({ page }) => {
  await page.route(`**${API}/plan?**`, route => route.fulfill({ status: 503, contentType: "application/json", body: "{}" }));
  await page.goto("/home");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "Thử lại gợi ý" })).toBeVisible();
  await expect(page.getByText("You are all set for today.")).toHaveCount(0);
});

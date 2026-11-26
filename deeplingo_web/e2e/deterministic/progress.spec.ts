import { expect, test } from "@playwright/test";
import { progressBody } from "./progressFixture";

// Progress renders the one /learner/me/progress endpoint and filters by language. Mocked: no live service.
const API = "/api/v1/v3/learner/me";

const ALL = progressBody({
  languages: ["en", "zh"],
  heatmap: [{ date: "2026-11-12", count: 4 }, { date: "2026-11-13", count: 2 }],
  streak: { current: 2, longest: 6, active_days: 2 },
  cards: [
    { language_code: "en", total: 5, due: 2, new: 1, learning: 1, review: 2, relearning: 1 },
    { language_code: "zh", total: 3, due: 1, new: 1, learning: 0, review: 2, relearning: 0 },
  ],
  accuracy: [{ kind: "choice", attempts: 4, correct: 3, accuracy: 75 }, { kind: "cloze", attempts: 2, correct: 1, accuracy: 50 }],
  pronunciation: [
    { date: "2026-11-12", pronunciation: 70, accuracy: 66, fluency: 74, completeness: 90, prosody: null, sessions: 2 },
    { date: "2026-11-13", pronunciation: 82.4, accuracy: 80, fluency: 85, completeness: 95, prosody: 70, sessions: 1 }],
  weak_words: ["water", "three"],
  grammar: { learned: 4, done_correctly: 3 }, regions_completed: 5, speaking: { sessions: 2, minutes: 12.5, weeks: [{ week_start: "2026-11-09", minutes: 12.5 }] },
});
const CHINESE = progressBody({
  language: "zh", languages: ["en", "zh"],
  heatmap: [{ date: "2026-11-13", count: 1 }], streak: { current: 1, longest: 1, active_days: 1 },
  cards: [{ language_code: "zh", total: 3, due: 1, new: 1, learning: 0, review: 2, relearning: 0 }],
  accuracy: [{ kind: "cloze", attempts: 1, correct: 0, accuracy: 0 }],
});

test("Progress shows the learner's numbers and filters them by language", async ({ page }) => {
  const asked: (string | null)[] = [];
  await page.addInitScript(() => {
    localStorage.setItem("deeplingo.ui_language", "en");
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "e2e-dummy.header.token", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: "e2e-user", aud: "authenticated", role: "authenticated",
        email: "preview@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    }));
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", declared_level: null, is_complete: true });
    if (url.pathname === `${API}/progress`) {
      const language = url.searchParams.get("language");
      asked.push(language);
      return json(language === "zh" ? CHINESE : ALL);
    }
    if (url.pathname.startsWith("/api/")) return json({});
    return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
  });

  await page.goto("/progress");
  await expect(page.getByRole("heading", { name: "Progress", level: 1 })).toBeVisible();
  const streak = page.locator(".progress-stat", { hasText: "Current streak" });
  await expect(streak.locator("strong")).toContainText("2");
  await expect(page.locator(".progress-stat", { hasText: "Speaking time" }).locator("strong")).toContainText("12.5");
  const cards = page.getByRole("region", { name: "Cards" });
  await expect(cards.locator(".progress-total")).toContainText("8 cards · 3 due now");
  await expect(page.getByRole("region", { name: "Accuracy" })).toContainText("75%");
  await expect(page.getByRole("region", { name: "Grammar" })).toContainText("4");
  await expect(page.getByRole("region", { name: "Video" })).toContainText("5");
  await expect(page.getByRole("table", { name: "Pronunciation scores by day" })).toContainText("2026-11-13");
  await expect(page.getByRole("region", { name: "Pronunciation" }).locator(".progress-metric")).toHaveCount(6); // five scores and sessions
  await expect(page.getByRole("region", { name: "Pronunciation" })).toContainText("water");
  await expect(page.getByRole("region", { name: "Speaking per week" }).locator(".progress-bars i")).toHaveCount(12);
  await expect(page.getByRole("region", { name: "Activity over time" }).locator(".progress-bars i")).toHaveCount(30);
  expect(asked).toEqual([null]);

  const filter = page.getByRole("group", { name: "Language" });
  await expect(filter.getByRole("button")).toHaveCount(3);
  await filter.getByRole("button").nth(2).click();
  await expect(cards.locator(".progress-total")).toContainText("3 cards · 1 due now");
  await expect(page.getByRole("region", { name: "Accuracy" })).toContainText("0%");
  await expect(streak.locator("strong")).toContainText("1");
  expect(asked).toEqual([null, "zh"]);
  // The filter keeps every language, and "All languages" goes back.
  await expect(filter.getByRole("button")).toHaveCount(3);
  await filter.getByRole("button", { name: "All languages" }).click();
  await expect(cards.locator(".progress-total")).toContainText("8 cards");
});

test("Progress says so when the numbers cannot be loaded", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("deeplingo.ui_language", "en");
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "e2e-dummy.header.token", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: "e2e-user", aud: "authenticated", role: "authenticated",
        email: "preview@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    }));
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", declared_level: null, is_complete: true });
    if (url.pathname === `${API}/progress`) return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    if (url.pathname.startsWith("/api/")) return json({});
    return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
  });
  await page.goto("/progress");
  await expect(page.getByRole("alert")).toContainText("Your progress could not be loaded.");
});
